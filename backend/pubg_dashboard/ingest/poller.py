"""Tracked-player poller.

The only rate-limited thing we do. PUBG keeps ~14 days of match history, so
this loop is the whole reason the archive exists: miss a fortnight and those
matches are gone permanently.

Budget: `GET /players` costs one token per request and takes up to 10 names, so
one cycle over a handful of tracked players costs one token. Everything
downstream (`/matches/{id}`, the telemetry CDN) is free.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import structlog
from sqlalchemy import Float, cast, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.config import Settings
from pubg_dashboard.db.models import Player, utcnow
from pubg_dashboard.ingest.ports import IngestContext
from pubg_dashboard.ingest.queue import enqueue_match_fetches
from pubg_dashboard.ingest.upsert import unknown_match_ids

log = structlog.get_logger(__name__)

# `GET /players?filter[playerNames]=` accepts at most 10 names per request.
MAX_NAMES_PER_REQUEST: Final = 10

# A player that keeps failing is almost always renamed or deleted, and those
# 404 forever. Back off exponentially from the poll interval up to this cap so
# one dead name cannot eat the rate-limit budget of the live ones.
MAX_BACKOFF_SECONDS: Final = 6 * 60 * 60
_MAX_BACKOFF_DOUBLINGS: Final = 16  # keeps power(2, n) away from float overflow


@dataclass(frozen=True, slots=True)
class DuePlayer:
    account_id: str
    name: str


@dataclass(frozen=True, slots=True)
class PlayerRef:
    """One `player` object from a `GET /players` response."""

    account_id: str
    name: str
    match_ids: tuple[str, ...]


@dataclass(slots=True)
class PollReport:
    polled: int = 0
    failed: int = 0
    new_matches: int = 0
    requests: int = 0


def parse_players_payload(payload: Mapping[str, Any]) -> list[PlayerRef]:
    """Flatten a `GET /players` response.

    `relationships.matches.data[]` holds the recent match ids, newest first —
    though the ordering is undocumented, so nothing here depends on it.
    """
    refs: list[PlayerRef] = []
    for item in payload.get("data") or ():
        attrs = item.get("attributes") or {}
        matches = ((item.get("relationships") or {}).get("matches") or {}).get("data") or ()
        refs.append(
            PlayerRef(
                account_id=str(item["id"]),
                name=str(attrs.get("name") or ""),
                match_ids=tuple(str(ref["id"]) for ref in matches),
            )
        )
    return refs


def _status_code(exc: BaseException) -> int | None:
    """HTTP status behind a client exception, whatever wrapper it arrived in."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _chunked(items: Sequence[DuePlayer], size: int) -> Iterable[Sequence[DuePlayer]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def select_due_players(
    session: AsyncSession, settings: Settings, limit: int
) -> list[DuePlayer]:
    """Tracked players whose backoff window has elapsed, stalest first."""
    base = float(settings.poll_interval_seconds)
    # least(base * 2^failures, cap) seconds, computed in SQL so the whole
    # backoff decision is one indexable predicate.
    backoff = func.least(
        cast(base, Float) * func.power(2.0, func.least(Player.consecutive_poll_failures, _MAX_BACKOFF_DOUBLINGS)),
        cast(float(MAX_BACKOFF_SECONDS), Float),
    ) * literal_column("interval '1 second'")

    stmt = (
        select(Player.account_id, Player.name)
        .where(
            Player.tracked.is_(True),
            Player.is_bot.is_(False),
            or_(
                Player.last_polled_at.is_(None),
                Player.last_polled_at <= func.now() - backoff,
            ),
        )
        # Plain ASC, i.e. NULLS LAST, because that is exactly what the partial
        # index ix_players_poll_queue stores; asking for NULLS FIRST would
        # force a sort. Never-polled players are still eligible and, at this
        # scale, land in the same cycle — their history comes from the
        # backfill_player job anyway.
        .order_by(Player.last_polled_at.asc())
        .limit(limit)
    )
    rows = await session.execute(stmt)
    return [DuePlayer(account_id=row.account_id, name=row.name) for row in rows]


async def _mark_polled(session: AsyncSession, matched: Sequence[tuple[DuePlayer, PlayerRef]]) -> None:
    if not matched:
        return
    await session.execute(
        update(Player)
        .where(Player.account_id.in_([player.account_id for player, _ in matched]))
        .values(last_polled_at=utcnow(), consecutive_poll_failures=0, last_poll_error=None)
    )
    for player, ref in matched:
        # In-game renames: the stored name is what we send next cycle, so a
        # stale one would 404 the whole batch from then on.
        if ref.account_id == player.account_id and ref.name and ref.name != player.name:
            await session.execute(
                update(Player).where(Player.account_id == player.account_id).values(name=ref.name)
            )
            log.info("poll.player_renamed", account_id=player.account_id, name=ref.name)


async def _mark_failed(session: AsyncSession, account_ids: Sequence[str], message: str) -> None:
    if not account_ids:
        return
    await session.execute(
        update(Player)
        .where(Player.account_id.in_(account_ids))
        .values(
            # Stamped even though the poll failed: the backoff window is
            # measured from the last *attempt*, not the last success.
            last_polled_at=utcnow(),
            consecutive_poll_failures=Player.consecutive_poll_failures + 1,
            last_poll_error=message[:1000],
        )
    )


async def _poll_batch(ctx: IngestContext, batch: Sequence[DuePlayer], report: PollReport) -> None:
    names = [player.name for player in batch]
    try:
        report.requests += 1
        payload = await ctx.api.get_players_by_names(names)
    except Exception as exc:  # noqa: BLE001 - one bad batch must not stop the cycle
        if _status_code(exc) == 404 and len(batch) > 1:
            # An unknown name 404s the ENTIRE batch, so one renamed account
            # would otherwise blind us to its nine batch-mates forever. Binary
            # split to isolate the offender: O(k log n) extra requests rather
            # than one per name.
            mid = len(batch) // 2
            await _poll_batch(ctx, batch[:mid], report)
            await _poll_batch(ctx, batch[mid:], report)
            return
        log.warning("poll.batch_failed", names=names, error=str(exc))
        async with ctx.sessionmaker() as session, session.begin():
            await _mark_failed(session, [player.account_id for player in batch], repr(exc))
        report.failed += len(batch)
        return

    refs = parse_players_payload(payload)
    by_id = {ref.account_id: ref for ref in refs}
    by_name = {ref.name: ref for ref in refs if ref.name}

    matched: list[tuple[DuePlayer, PlayerRef]] = []
    missing: list[DuePlayer] = []
    for player in batch:
        # Match on account id first; fall back to the (case-sensitive) name for
        # rows added by name before their id was ever resolved.
        ref = by_id.get(player.account_id) or by_name.get(player.name)
        if ref is None:
            missing.append(player)
        else:
            matched.append((player, ref))

    seen: list[str] = []
    for _, ref in matched:
        seen.extend(ref.match_ids)

    async with ctx.sessionmaker() as session, session.begin():
        # One existence query for every id the batch reported, not one per id.
        new_ids = await unknown_match_ids(session, seen)
        report.new_matches += await enqueue_match_fetches(session, new_ids)
        await _mark_polled(session, matched)
        await _mark_failed(
            session, [player.account_id for player in missing], "not returned by /players"
        )

    report.polled += len(matched)
    report.failed += len(missing)


async def poll_once(ctx: IngestContext, *, limit: int | None = None) -> PollReport:
    """Run one polling cycle over every tracked player that is due."""
    settings = ctx.settings
    if limit is None:
        # At most one minute of rate-limit budget per cycle: one request covers
        # 10 names, and the bucket refills `pubg_rate_limit_per_min` per minute.
        limit = MAX_NAMES_PER_REQUEST * max(1, settings.pubg_rate_limit_per_min)

    async with ctx.sessionmaker() as session:
        due = await select_due_players(session, settings, limit)

    report = PollReport()
    if not due:
        return report

    for batch in _chunked(due, MAX_NAMES_PER_REQUEST):
        await _poll_batch(ctx, batch, report)

    log.info(
        "poll.cycle",
        due=len(due),
        polled=report.polled,
        failed=report.failed,
        new_matches=report.new_matches,
        requests=report.requests,
    )
    return report


async def run_poller(ctx: IngestContext, *, stop: asyncio.Event | None = None) -> None:
    """Poll forever, sleeping `poll_interval_seconds` between cycles."""
    stop = stop or asyncio.Event()
    interval = float(ctx.settings.poll_interval_seconds)

    while not stop.is_set():
        try:
            await poll_once(ctx)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the poller must outlive any single cycle
            log.exception("poll.cycle_failed")

        # Interruptible sleep: SIGTERM should not wait out a 5 minute interval.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
