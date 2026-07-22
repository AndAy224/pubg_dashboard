"""Operator CLI (`pubgd`).

Every command is a thin synchronous shell: typer/click parse the arguments,
:func:`_run` owns the event loop, and the handful of failures an operator
actually hits — Postgres down, migrations not applied, API key missing, a name
typed with the wrong case — are converted into one actionable line instead of a
traceback.

Output uses typer/click primitives only. typer bundles rich, but fixed-width
columns pipe cleanly into `grep`/`less` and never wrap a 36-character match id
onto a second line, which is what an operator is usually staring at.

Modules that this CLI only *drives* (the poller, the worker, the archive
importer, the PUBG client) are imported lazily inside the command that needs
them, so a broken or not-yet-written subsystem cannot stop `pubgd stats` from
answering "what is in the database".
"""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import itertools
import pathlib
import re
import socket
from collections.abc import AsyncIterator, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from types import ModuleType
from typing import Annotated, Any, NoReturn

import typer
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pubg_dashboard.config import Settings, get_settings
from pubg_dashboard.db.models import Job, Match, Participant, Player, utcnow

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

JOB_KINDS: tuple[str, ...] = (
    "fetch_match",
    "fetch_telemetry",
    "parse_telemetry",
    "backfill_player",
)
JOB_STATES: tuple[str, ...] = ("pending", "running", "done", "failed", "dead")
LIVE_JOB_STATES: tuple[str, ...] = ("pending", "running")
# `db/models.py` calls the terminal-failure state "failed"; `docs/BUILD-SPEC.md`
# §2.8 calls it "dead". Retry accepts both so this command keeps working
# whichever name the migration settles on.
RETRYABLE_STATES: tuple[str, ...] = ("failed", "dead")

# GET /players?filter[playerNames]= accepts at most 10 names per request.
PLAYER_NAME_BATCH = 10


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def _ok(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


def _warn(message: str) -> None:
    typer.secho(message, fg=typer.colors.YELLOW)


def _dim(message: str) -> None:
    typer.secho(message, fg=typer.colors.BRIGHT_BLACK)


def _fatal(message: str, *, hint: str | None = None) -> NoReturn:
    """Print an error plus what to do about it, then exit non-zero."""
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    if hint:
        typer.secho(f"  -> {hint}", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


def _section(title: str) -> None:
    typer.secho(f"\n{title}", bold=True)


def _kv(label: str, value: str, width: int = 16) -> None:
    typer.echo(f"  {label.ljust(width)} {value}")


def _table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    align: str = "",
    empty: str = "(none)",
) -> None:
    """Fixed-width table. `align` is one char per column: 'l' or 'r'."""
    if not rows:
        _dim(f"  {empty}")
        return
    align = align.ljust(len(headers), "l")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(cells: Sequence[str]) -> str:
        parts = (
            cell.rjust(widths[i]) if align[i] == "r" else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        )
        return "  " + "  ".join(parts).rstrip()

    typer.secho(line(headers), bold=True)
    _dim(line(["-" * w for w in widths]))
    for row in rows:
        typer.echo(line(row))


def _truncate(text_: str, limit: int) -> str:
    return text_ if len(text_) <= limit else text_[: limit - 3] + "..."


def _fmt_bytes(n: int | None) -> str:
    size = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86_400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86_400}d"


def _ago(ts: dt.datetime | None) -> str:
    if ts is None:
        return "never"
    delta = int((utcnow() - ts).total_seconds())
    return f"in {_fmt_duration(-delta)}" if delta < 0 else f"{_fmt_duration(delta)} ago"


def _fmt_day(ts: dt.datetime | None) -> str:
    return ts.astimezone().strftime("%Y-%m-%d") if ts else "-"


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def _redact(dsn: str) -> str:
    """Strip the password out of a DSN before it lands in an error message."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    """One engine per CLI invocation, disposed on the way out.

    NullPool because a CLI command uses exactly one connection and then exits;
    a pool would only add a shutdown race with the event loop.
    """
    engine = create_async_engine(
        get_settings().database_url,
        poolclass=NullPool,
        connect_args={
            # Without an explicit connect timeout a stopped Postgres container
            # makes `pubgd stats` hang instead of saying what is wrong.
            "timeout": 10,
            "server_settings": {"application_name": "pubgd-cli", "jit": "off"},
        },
    )
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _fatal_db(exc: BaseException) -> NoReturn:
    """Turn a driver-level failure into an instruction."""
    dsn = _redact(get_settings().database_url)
    orig = getattr(exc, "orig", None) or exc
    # asyncpg exposes the five-character SQLSTATE; SQLAlchemy wraps the
    # exception but keeps the original on `.orig`.
    match getattr(orig, "sqlstate", None):
        case "3D000":
            _fatal(
                f"the database named in {dsn} does not exist.",
                hint="check DATABASE_URL in .env, then `uv run alembic upgrade head`",
            )
        case "28P01" | "28000":
            _fatal(
                f"Postgres rejected the credentials in {dsn}.",
                hint=(
                    "POSTGRES_USER/POSTGRES_PASSWORD must match what the volume was created "
                    "with; `docker compose down -v && docker compose up -d` recreates it"
                ),
            )
        case "42P01" | "42703":
            _fatal(
                f"the schema is missing or behind the models ({orig}).",
                hint="uv run alembic upgrade head",
            )
    _fatal(
        f"cannot reach Postgres at {dsn} ({type(orig).__name__}: {orig}).",
        hint="is `docker compose up -d` running?  check with `docker compose ps`",
    )


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run one command coroutine and translate the predictable failures."""
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        _warn("\ninterrupted")
        raise typer.Exit(code=130) from None
    except (SQLAlchemyError, ConnectionRefusedError, socket.gaierror, TimeoutError) as exc:
        _fatal_db(exc)


# --------------------------------------------------------------------------- #
# Lazy imports of the subsystems this CLI drives
# --------------------------------------------------------------------------- #


def _import(dotted: str, *, needed_for: str) -> ModuleType:
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        _fatal(
            f"`pubgd {needed_for}` needs {dotted}, which cannot be imported ({exc.msg}).",
            hint="run `uv sync` in backend/ — or that module is not built yet",
        )
    except ImportError as exc:  # module exists but its own imports are broken
        _fatal(f"{dotted} failed to import: {exc}")


def _symbol(module: ModuleType, name: str, *, needed_for: str) -> Any:
    try:
        return getattr(module, name)
    except AttributeError:
        _fatal(f"`pubgd {needed_for}` expects {module.__name__}.{name}, which does not exist.")


# --------------------------------------------------------------------------- #
# PUBG API
# --------------------------------------------------------------------------- #


def _pubg_client(settings: Settings, shard: str, *, needed_for: str) -> Any:
    """Build the API client.

    Single place to reconcile with `pubg/client.py`'s real constructor.
    """
    if not settings.pubg_api_key:
        _fatal(
            "PUBG_API_KEY is empty.",
            hint="add it to the .env at the repo root (keys: https://developer.pubg.com)",
        )
    module = _import("pubg_dashboard.pubg.client", needed_for=needed_for)
    client_cls = _symbol(module, "PubgClient", needed_for=needed_for)
    return client_cls(
        api_key=settings.pubg_api_key,
        shard=shard,
        rate_limit_per_min=settings.pubg_rate_limit_per_min,
    )


def _unpack_player(raw: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    """`(account_id, name, match_ids)` out of whatever shape the client returns.

    `PubgClient.get_players_by_name()` returns "parsed dicts" whose key style is
    not pinned yet, so snake_case, camelCase and the raw JSON:API object are all
    accepted. A key mismatch here would be a silent empty string rather than a
    crash, which is why it is worth handling explicitly.
    """
    attributes = raw.get("attributes") or {}
    account_id = str(raw.get("account_id") or raw.get("accountId") or raw.get("id") or "")
    name = str(raw.get("name") or attributes.get("name") or "")
    match_ids = raw.get("match_ids") or raw.get("matchIds")
    if match_ids is None:
        related = ((raw.get("relationships") or {}).get("matches") or {}).get("data") or []
        match_ids = [m["id"] for m in related if isinstance(m, Mapping) and "id" in m]
    return account_id, name, [str(m) for m in match_ids]


async def _resolve_chunk(
    client: Any,
    chunk: Sequence[str],
    shard: str,
    not_found: type[Exception],
    found: list[Mapping[str, Any]],
    missing: list[str],
) -> None:
    """Resolve <=10 names, isolating the ones that do not exist.

    A single unknown name 404s the **entire** batch, so a failure says nothing
    about the other nine names. If the client can attribute the 404 to specific
    names we drop those and retry the rest as one batch; otherwise we fall back
    to one request per name. Either way the extra rate-limit tokens are only
    spent on the error path.
    """
    try:
        found.extend(await client.get_players_by_name(list(chunk), shard=shard))
        return
    except not_found as exc:
        blamed = {n for n in chunk if n in set(getattr(exc, "names", None) or ())}

    if not blamed:
        for name in chunk:
            try:
                found.extend(await client.get_players_by_name([name], shard=shard))
            except not_found:
                missing.append(name)
        return

    missing.extend(n for n in chunk if n in blamed)
    remaining = [n for n in chunk if n not in blamed]
    if remaining:
        await _resolve_chunk(client, remaining, shard, not_found, found, missing)


async def _resolve_names(
    names: Sequence[str], shard: str, *, needed_for: str
) -> tuple[list[Mapping[str, Any]], list[str]]:
    settings = get_settings()
    errors = _import("pubg_dashboard.pubg.errors", needed_for=needed_for)
    not_found = _symbol(errors, "PlayerNotFound", needed_for=needed_for)

    found: list[Mapping[str, Any]] = []
    missing: list[str] = []
    client = _pubg_client(settings, shard, needed_for=needed_for)
    try:
        for chunk in itertools.batched(names, PLAYER_NAME_BATCH):
            await _resolve_chunk(client, chunk, shard, not_found, found, missing)
    finally:
        await client.aclose()
    return found, missing


def _explain_unresolved(names: Sequence[str], shard: str) -> None:
    _warn(f"could not resolve on shard '{shard}': {', '.join(names)}")
    _dim("  Player names are CASE-SENSITIVE: 'chocotaco' and 'chocoTaco' are different lookups.")
    _dim("  Copy the name exactly as it appears in game.")
    _dim(f"  If the case is right, the account may have been renamed, or it is not on '{shard}'")
    _dim("  (try --shard xbox / psn / kakao).")


# --------------------------------------------------------------------------- #
# Job queue
# --------------------------------------------------------------------------- #


async def _enqueue(session: AsyncSession, *, kind: str, payload: dict[str, Any], key: str) -> bool:
    """Insert a job unless the same unit of work is already live.

    Deliberately a SELECT-then-INSERT rather than ON CONFLICT DO NOTHING: the
    live-job uniqueness is enforced by a *partial* index, and ON CONFLICT can
    only infer a partial index if the statement repeats its exact column list
    and predicate. The CLI is a single operator running one command, so the
    IntegrityError fallback below covers the race that a worker could lose.
    """
    if await _has_live_twin(session, kind, key):
        return False
    try:
        # A SAVEPOINT, not a plain flush: a constraint violation must not roll
        # back the player row this job was enqueued alongside.
        async with session.begin_nested():
            session.add(Job(kind=kind, payload=payload, dedupe_key=key, state="pending"))
    except IntegrityError:
        return False
    return True


def _dedupe_key(kind: str, ident: str) -> str:
    """Prefix the kind into the key.

    `models.py` makes `dedupe_key` unique on its own while BUILD-SPEC §2.8 makes
    it unique per `(kind, dedupe_key)`. Prefixing satisfies both.
    """
    return f"{kind}:{ident}"


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = typer.Typer(
    name="pubgd",
    help="Operator CLI for the self-hosted PUBG dashboard.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
player_app = typer.Typer(help="Add, remove and inspect tracked players.", no_args_is_help=True)
jobs_app = typer.Typer(help="Inspect and repair the job queue.", invoke_without_command=True)
app.add_typer(player_app, name="player")
app.add_typer(jobs_app, name="jobs")


# --------------------------------------------------------------------------- #
# player
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class TrackResult:
    name: str
    status: str
    account_id: str = "-"
    match_ids: int = 0
    queued: bool = False


@dataclass(slots=True)
class TrackReport:
    results: list[TrackResult] = field(default_factory=list)

    @property
    def unresolved(self) -> list[str]:
        return [r.name for r in self.results if r.status == "not found"]


async def _track(names: Sequence[str], shard: str, *, needed_for: str) -> TrackReport:
    """Resolve names, upsert the players as tracked, queue their backfill."""
    found, missing = await _resolve_names(names, shard, needed_for=needed_for)
    report = TrackReport([TrackResult(name=n, status="not found") for n in missing])

    resolved_lower: set[str] = set()
    async with _session() as session:
        for raw in found:
            account_id, canonical, match_ids = _unpack_player(raw)
            if not account_id:
                report.results.append(TrackResult(name=canonical or "?", status="no account id"))
                continue
            resolved_lower.add(canonical.lower())

            player = await session.get(Player, account_id)
            if player is None:
                player = Player(account_id=account_id, name=canonical, shard=shard, tracked=True)
                session.add(player)
                status = "added"
            else:
                status = "already tracked" if player.tracked else "re-tracked"
                # PUBG names are mutable; the account id is the stable key, so a
                # rename shows up here as a name change on an existing row.
                player.name = canonical
                player.shard = shard
                player.tracked = True
                # A previously failing name that resolves again starts clean, or
                # the poller's backoff keeps punishing it for old failures.
                player.last_poll_error = None
                player.consecutive_poll_failures = 0

            queued = await _enqueue(
                session,
                kind="backfill_player",
                # The match ids came free with the name resolution we already
                # paid a token for; handing them over saves the backfill job a
                # second /players call.
                payload={
                    "account_id": account_id,
                    "shard": shard,
                    "name": canonical,
                    "match_ids": match_ids,
                },
                key=_dedupe_key("backfill_player", account_id),
            )
            report.results.append(
                TrackResult(
                    name=canonical,
                    status=status,
                    account_id=account_id,
                    match_ids=len(match_ids),
                    queued=queued,
                )
            )
        await session.commit()

    # The API also answers 200 with an empty `data` array for a name it does not
    # know, so anything we asked for and did not get back is missing too.
    for name in names:
        if name.lower() not in resolved_lower and name not in report.unresolved:
            report.results.append(TrackResult(name=name, status="not found"))
    return report


@player_app.command("add")
def player_add(
    name: Annotated[str, typer.Argument(help="Exact in-game name (case-sensitive).")],
    shard: Annotated[
        str | None, typer.Option("--shard", help="Platform shard. Default: from settings.")
    ] = None,
) -> None:
    """Track a player: resolve the name, store the account, queue a backfill."""
    shard = shard or get_settings().pubg_default_shard
    report = _run(_track([name], shard, needed_for="player add"))

    if report.unresolved:
        _explain_unresolved(report.unresolved, shard)
        raise typer.Exit(code=1)

    for result in report.results:
        if result.status == "no account id":
            _fatal(f"the API returned a player without an account id for '{result.name}'.")
        _ok(f"{result.status}: {result.name}  {result.account_id}  ({shard})")
        if result.queued:
            _dim(f"  queued backfill_player for {result.match_ids} recent match ids")
        else:
            _dim("  backfill already queued (a live job for this account exists)")
    _dim("  run `pubgd worker` to drain the queue, or `pubgd poll` to keep it fed")


@player_app.command("remove")
def player_remove(
    name: Annotated[str, typer.Argument(help="Tracked player name (case-insensitive).")],
) -> None:
    """Stop tracking a player. Match history is never deleted."""
    _run(_player_remove(name))


async def _player_remove(name: str) -> None:
    async with _session() as session:
        # Case-insensitive on purpose: untracking is not destructive, and it uses
        # the ix_players_name_lower index. Matches the `lower(name)` index shape.
        stmt = (
            update(Player)
            .where(func.lower(Player.name) == name.lower(), Player.tracked)
            .values(tracked=False)
            .returning(Player.name, Player.account_id)
        )
        rows = (await session.execute(stmt)).all()
        await session.commit()

    if not rows:
        _warn(f"no tracked player named '{name}'.")
        _dim("  `pubgd player list` shows who is tracked.")
        raise typer.Exit(code=1)
    for row_name, account_id in rows:
        _ok(f"untracked: {row_name}  {account_id}")
    _dim("  their matches, participants and telemetry stay in the database")


@player_app.command("list")
def player_list() -> None:
    """Show tracked players and how far behind their polling is."""
    _run(_player_list())


async def _player_list() -> None:
    stmt = (
        select(
            Player.name,
            Player.account_id,
            Player.shard,
            func.count(Participant.match_id).label("matches"),
            Player.last_polled_at,
            Player.consecutive_poll_failures,
            Player.last_poll_error,
        )
        # Explicit ON clause: participants.account_id is a plain column, and this
        # must keep working if its FK to players is dropped for bot safety.
        .outerjoin(Participant, Participant.account_id == Player.account_id)
        .where(Player.tracked)
        # Grouping by the primary key is enough for Postgres; every other
        # selected player column is functionally dependent on it.
        .group_by(Player.account_id)
        .order_by(Player.name)
    )
    async with _session() as session:
        rows = (await session.execute(stmt)).all()

    if not rows:
        _warn("no tracked players.")
        _dim("  pubgd player add <ExactName>      (or `pubgd seed` to add PUBG_SEED_PLAYERS)")
        return

    _table(
        ["NAME", "ACCOUNT ID", "SHARD", "MATCHES", "LAST POLLED", "FAILS"],
        [
            [name, account_id, shard, str(matches), _ago(polled), str(fails)]
            for name, account_id, shard, matches, polled, fails, _ in rows
        ],
        align="lllrrr",
    )
    failing = [(name, err) for name, _, _, _, _, fails, err in rows if fails and err]
    if failing:
        _section("POLL ERRORS")
        for name, err in failing:
            _warn(f"  {name}: {_truncate(err, 90)}")


@app.command("seed")
def seed() -> None:
    """Track every name in PUBG_SEED_PLAYERS."""
    settings = get_settings()
    if not settings.pubg_seed_players:
        _warn("PUBG_SEED_PLAYERS is empty.")
        _dim("  set it in .env as a comma-separated list, e.g. PUBG_SEED_PLAYERS=Alice,Bob")
        raise typer.Exit(code=1)

    shard = settings.pubg_default_shard
    names = settings.pubg_seed_players
    _dim(f"resolving {len(names)} name(s) on shard '{shard}'...")
    report = _run(_track(names, shard, needed_for="seed"))

    _table(
        ["NAME", "STATUS", "ACCOUNT ID", "MATCHES", "BACKFILL"],
        [
            [r.name, r.status, r.account_id, str(r.match_ids), "queued" if r.queued else "-"]
            for r in sorted(report.results, key=lambda r: r.name.lower())
        ],
        align="lllrl",
    )
    if report.unresolved:
        _explain_unresolved(report.unresolved, shard)
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# poll / worker / import
# --------------------------------------------------------------------------- #


@app.command("poll")
def poll(
    once: Annotated[bool, typer.Option("--once", help="Run one cycle and exit.")] = False,
) -> None:
    """Poll tracked players for new matches and enqueue them."""
    settings = get_settings()
    tracked = _run(_count_tracked())
    if not tracked:
        _warn("no tracked players — the poller would have nothing to do.")
        _dim("  pubgd player add <ExactName>")
        raise typer.Exit(code=1)

    module = _import("pubg_dashboard.ingest.poller", needed_for="poll")
    run_poller = _symbol(module, "run_poller", needed_for="poll")
    if once:
        _dim(f"polling {tracked} tracked player(s), one cycle")
    else:
        _dim(
            f"polling {tracked} tracked player(s) every {settings.poll_interval_seconds}s "
            f"(rate limit {settings.pubg_rate_limit_per_min}/min) - ctrl-c to stop"
        )
    _run(run_poller(once=once))
    _ok("poll finished" if once else "poller stopped")


async def _count_tracked() -> int:
    async with _session() as session:
        return await session.scalar(
            select(func.count()).select_from(Player).where(Player.tracked)
        ) or 0


@app.command("worker")
def worker(
    concurrency: Annotated[
        int, typer.Option("--concurrency", "-c", min=1, max=32, help="Jobs run in parallel.")
    ] = 4,
    kinds: Annotated[
        str | None,
        typer.Option("--kinds", help="Comma-separated job kinds. Default: all."),
    ] = None,
) -> None:
    """Run the job worker until interrupted."""
    selected: list[str] | None = None
    if kinds:
        selected = [k.strip() for k in kinds.split(",") if k.strip()]
        unknown = [k for k in selected if k not in JOB_KINDS]
        if unknown:
            _fatal(
                f"unknown job kind(s): {', '.join(unknown)}",
                hint=f"valid kinds: {', '.join(JOB_KINDS)}",
            )

    module = _import("pubg_dashboard.jobs.worker", needed_for="worker")
    run_worker = _symbol(module, "run_worker", needed_for="worker")
    _dim(f"worker: concurrency={concurrency} kinds={','.join(selected) if selected else 'all'}")
    _run(run_worker(concurrency=concurrency, kinds=selected))
    _ok("worker stopped")


@app.command("import-archive")
def import_archive_cmd(
    matches_dir: Annotated[
        pathlib.Path | None, typer.Option("--matches-dir", help="Raw /matches/{id} JSON.")
    ] = None,
    telemetry_dir: Annotated[
        pathlib.Path | None, typer.Option("--telemetry-dir", help="Raw gzipped telemetry.")
    ] = None,
) -> None:
    """Ingest the on-disk archive written before the 14-day window closed."""
    settings = get_settings()
    matches = matches_dir or settings.match_archive_dir
    telemetry = telemetry_dir or settings.telemetry_dir

    if not matches.is_dir():
        _fatal(
            f"{matches} does not exist.",
            hint="pass --matches-dir, or run scripts/panic_archive.py first",
        )
    match_files = sorted(matches.glob("*.json"))
    telemetry_files = sorted(telemetry.glob("*.json.gz")) if telemetry.is_dir() else []
    if not match_files:
        _fatal(f"no *.json match files in {matches}.")

    _dim(f"importing {len(match_files)} match file(s) from {matches}")
    _dim(f"          {len(telemetry_files)} telemetry file(s) from {telemetry}")

    module = _import("pubg_dashboard.ingest.importer", needed_for="import-archive")
    import_archive = _symbol(module, "import_archive", needed_for="import-archive")

    # `import_archive` takes the session as its first positional argument and
    # commits per match, so the caller owns the connection. Every other command
    # in this file goes through `_session()`; this one used to call straight
    # into the coroutine and died with "missing 1 required positional
    # argument: 'session'".
    async def _do() -> Any:
        async with _session() as session:
            return await import_archive(
                session, matches_dir=matches, telemetry_dir=telemetry
            )

    summary = _run(_do())

    if is_dataclass(summary) and not isinstance(summary, type):
        _section("IMPORTED")
        for field in fields(summary):
            _kv(field.name.replace("_", " "), str(getattr(summary, field.name)))
    elif isinstance(summary, Mapping):
        _section("IMPORTED")
        for key, value in summary.items():
            _kv(str(key), str(value))
    elif summary is not None:
        typer.echo(str(summary))
    _ok("import complete")
    _dim("  `pubgd jobs` shows the parse work this queued")


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #


@jobs_app.callback(invoke_without_command=True)
def jobs_main(
    ctx: typer.Context,
    state: Annotated[
        str | None, typer.Option("--state", help="Only this state; also lists the rows.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Rows to list with --state.")] = 20,
) -> None:
    """Show queue depth by kind and state."""
    if ctx.invoked_subcommand is not None:
        return
    if state and state not in JOB_STATES:
        _fatal(f"unknown state '{state}'.", hint=f"valid states: {', '.join(JOB_STATES)}")
    _run(_jobs_list(state, limit))


async def _jobs_list(state: str | None, limit: int) -> None:
    counts_stmt = select(Job.kind, Job.state, func.count()).group_by(Job.kind, Job.state)
    if state:
        counts_stmt = counts_stmt.where(Job.state == state)

    async with _session() as session:
        counts = (await session.execute(counts_stmt)).all()
        rows: Sequence[Any] = ()
        if state:
            rows = (
                await session.execute(
                    select(
                        Job.id,
                        Job.kind,
                        Job.dedupe_key,
                        Job.attempts,
                        Job.max_attempts,
                        Job.run_after,
                        Job.last_error,
                    )
                    .where(Job.state == state)
                    .order_by(Job.run_after, Job.id)
                    .limit(limit)
                )
            ).all()

    if not counts:
        _warn("the queue is empty." if not state else f"no jobs in state '{state}'.")
        _dim("  `pubgd player add <name>` or `pubgd import-archive` create work")
        return

    tally = {(kind, st): n for kind, st, n in counts}
    seen_states = {st for _, st in tally}
    # Known states first, then anything the schema grew since this file was written.
    columns = [s for s in JOB_STATES if s in seen_states] + sorted(seen_states - set(JOB_STATES))
    kinds = sorted({kind for kind, _ in tally})

    _section("QUEUE")
    body = [
        [kind, *[str(tally.get((kind, col), 0)) for col in columns]]
        for kind in kinds
    ]
    body.append(
        ["TOTAL", *[str(sum(tally.get((k, col), 0) for k in kinds)) for col in columns]]
    )
    _table(
        ["KIND", *[c.upper() for c in columns]],
        body,
        align="l" + "r" * len(columns),
    )

    if state:
        _section(f"{state.upper()} JOBS (oldest {len(rows)})")
        _table(
            ["ID", "KIND", "DEDUPE KEY", "TRIES", "RUN AFTER", "LAST ERROR"],
            [
                [
                    str(job_id),
                    kind,
                    _truncate(key, 44),
                    f"{attempts}/{max_attempts}",
                    _ago(run_after),
                    _truncate(err or "-", 60),
                ]
                for job_id, kind, key, attempts, max_attempts, run_after, err in rows
            ],
            align="rllrll",
        )


@jobs_app.command("retry")
def jobs_retry(
    job_id: Annotated[int | None, typer.Argument(help="Job id to reset.")] = None,
    all_failed: Annotated[
        bool, typer.Option("--all-failed", help="Reset every failed job.")
    ] = False,
) -> None:
    """Reset failed jobs to pending."""
    if job_id is None and not all_failed:
        _fatal(
            "nothing to retry.",
            hint="pubgd jobs retry <id>   |   pubgd jobs retry --all-failed",
        )
    if job_id is not None and all_failed:
        _fatal("pass either a job id or --all-failed, not both.")
    _run(_jobs_retry(job_id, all_failed))


def _reset_values() -> dict[str, Any]:
    return {
        "state": "pending",
        "attempts": 0,
        "last_error": None,
        "locked_at": None,
        "locked_by": None,
        "finished_at": None,
        "run_after": utcnow(),
    }


async def _jobs_retry(job_id: int | None, all_failed: bool) -> None:
    async with _session() as session:
        if job_id is not None:
            job = await session.get(Job, job_id)
            if job is None:
                _fatal(f"no job with id {job_id}.", hint="`pubgd jobs --state failed` lists them")
            if job.state not in RETRYABLE_STATES:
                _fatal(
                    f"job {job_id} is '{job.state}', not failed.",
                    hint="only failed jobs can be retried",
                )
            if await _has_live_twin(session, job.kind, job.dedupe_key):
                _fatal(
                    f"job {job_id} cannot be revived: another {job.kind} job for "
                    f"'{job.dedupe_key}' is already pending or running.",
                    hint="that live job will do the same work — nothing to fix",
                )
            for key, value in _reset_values().items():
                setattr(job, key, value)
            await session.commit()
            _ok(f"job {job_id} ({job.kind}) reset to pending")
            return

        failed = (
            await session.execute(
                select(Job.id, Job.kind, Job.dedupe_key)
                .where(Job.state.in_(RETRYABLE_STATES))
                .order_by(Job.id)
            )
        ).all()
        if not failed:
            _ok("no failed jobs.")
            return

        # Reviving two jobs that share a live key would violate the partial
        # unique index, so keep the first per (kind, dedupe_key) and skip the
        # rest along with any key that already has a pending/running job.
        live = {
            (kind, key)
            for kind, key in (
                await session.execute(
                    select(Job.kind, Job.dedupe_key).where(Job.state.in_(LIVE_JOB_STATES))
                )
            ).all()
        }
        revive: list[int] = []
        for job_id_, kind, key in failed:
            if (kind, key) in live:
                continue
            live.add((kind, key))
            revive.append(job_id_)

        if revive:
            await session.execute(update(Job).where(Job.id.in_(revive)).values(**_reset_values()))
            await session.commit()

    _ok(f"reset {len(revive)} job(s) to pending")
    skipped = len(failed) - len(revive)
    if skipped:
        _dim(f"  skipped {skipped} whose work is already queued under the same dedupe key")
    if revive:
        _dim("  run `pubgd worker` to drain them")


async def _has_live_twin(session: AsyncSession, kind: str, key: str) -> bool:
    return (
        await session.scalar(
            select(Job.id)
            .where(Job.kind == kind, Job.dedupe_key == key, Job.state.in_(LIVE_JOB_STATES))
            .limit(1)
        )
    ) is not None


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #


@app.command("stats")
def stats() -> None:
    """Summarise what is actually in the database."""
    _run(_stats())


async def _stats() -> None:
    settings = get_settings()
    async with _session() as session:
        players_total, players_tracked = (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(Player.tracked),
                ).select_from(Player)
            )
        ).one()

        matches_by_type = (
            await session.execute(
                select(
                    Match.match_type,
                    func.count(),
                    func.min(Match.played_at),
                    func.max(Match.played_at),
                )
                .group_by(Match.match_type)
                .order_by(func.count().desc())
            )
        ).all()

        participants_total, participants_bots = (
            await session.execute(
                select(func.count(), func.count().filter(Participant.is_bot)).select_from(
                    Participant
                )
            )
        ).one()

        matches_total, tele_stored, tele_parsed, tele_bytes = (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(Match.telemetry_key.is_not(None)),
                    func.count().filter(Match.telemetry_parsed_at.is_not(None)),
                    func.coalesce(func.sum(Match.telemetry_bytes), 0),
                ).select_from(Match)
            )
        ).one()

        jobs_by_state = (
            await session.execute(select(Job.state, func.count()).group_by(Job.state))
        ).all()

    _section("PLAYERS")
    _kv("tracked", str(players_tracked))
    _kv("known accounts", str(players_total))

    _section(f"MATCHES ({matches_total})")
    _table(
        ["MATCH TYPE", "COUNT", "FIRST", "LAST"],
        [
            [match_type, str(count), _fmt_day(first), _fmt_day(last)]
            for match_type, count, first, last in matches_by_type
        ],
        align="lrll",
        empty="no matches yet - run `pubgd import-archive` or `pubgd poll --once`",
    )
    # Only `official` counts toward career stats; the other types are archived
    # but excluded from every aggregate.
    if any(t not in ("official",) for t, *_ in matches_by_type):
        _dim("  career stats count 'official' only")

    _section("PARTICIPANTS")
    _kv("total", str(participants_total))
    _kv("bots", f"{participants_bots}  ({_pct(participants_bots, participants_total)})")
    _kv("humans", str(participants_total - participants_bots))

    _section("TELEMETRY")
    _kv("stored", f"{tele_stored} / {matches_total} matches")
    _kv("parsed", f"{tele_parsed} / {matches_total} matches")
    _kv("bytes", _fmt_bytes(tele_bytes))
    location = (
        f"{settings.minio_endpoint} bucket '{settings.minio_bucket}'"
        if settings.storage_backend == "minio"
        else str(settings.telemetry_dir)
    )
    _kv("backend", f"{settings.storage_backend}  {location}")
    if tele_stored > tele_parsed:
        _dim(f"  {tele_stored - tele_parsed} match(es) fetched but not parsed - `pubgd worker`")

    _section("JOBS")
    if jobs_by_state:
        _kv("", "  ".join(f"{state}={count}" for state, count in sorted(jobs_by_state)))
    else:
        _dim("  queue empty")


if __name__ == "__main__":  # pragma: no cover
    app()
