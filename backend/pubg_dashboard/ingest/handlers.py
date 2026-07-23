"""Job handlers, registered with the worker.

Pipeline: `backfill_player` / the poller queue `fetch_match`, which queues
`fetch_telemetry`, which queues `parse_telemetry` (Phase 3).

Two rules every handler obeys:
  * network calls happen *outside* any open transaction — a multi-second
    telemetry download inside one would block VACUUM database-wide;
  * each handler owns its own `AsyncSession`, because one session is not safe
    for concurrent tasks and the worker runs handlers concurrently.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import gzip
from collections.abc import MutableMapping
from typing import Any, Final

import structlog
from sqlalchemy import select, update

from pubg_dashboard.db.models import Match, Player, utcnow
from pubg_dashboard.ingest.poller import parse_players_payload
from pubg_dashboard.ingest.ports import Handler, IngestContext, JobLike
from pubg_dashboard.ingest.queue import (
    JOB_BACKFILL_PLAYER,
    JOB_FETCH_MATCH,
    JOB_FETCH_TELEMETRY,
    JOB_PARSE_TELEMETRY,
    dedupe_key,
    enqueue,
    enqueue_match_fetches,
)
from pubg_dashboard.ingest.upsert import unknown_match_ids, upsert_match

log = structlog.get_logger(__name__)

_GZIP_MAGIC: Final = b"\x1f\x8b"


class MissingMatchError(RuntimeError):
    """A telemetry job ran before its match row existed."""


# ---------------------------------------------------------------------------
# fetch_match
# ---------------------------------------------------------------------------
async def fetch_match(ctx: IngestContext, match_id: str) -> None:
    """`GET /matches/{id}` -> upsert -> queue the telemetry download.

    This endpoint returns no rate-limit headers and is not rate limited, so it
    never spends limiter budget; the client is responsible for honouring that.
    """
    payload = await ctx.api.get_match(match_id)

    async with ctx.sessionmaker() as session, session.begin():
        match = await upsert_match(session, payload)
        # Same transaction as the data it depends on: no telemetry job for a
        # match that rolled back, no ingested match without a follow-up job.
        if match.telemetry_url and match.telemetry_key is None:
            await enqueue(
                session,
                JOB_FETCH_TELEMETRY,
                {"match_id": match_id},
                key=dedupe_key(JOB_FETCH_TELEMETRY, match_id),
            )
        elif not match.telemetry_url:
            log.warning("ingest.no_telemetry_asset", match_id=match_id)


# ---------------------------------------------------------------------------
# fetch_telemetry
# ---------------------------------------------------------------------------
async def fetch_telemetry(ctx: IngestContext, match_id: str) -> None:
    """Download the telemetry asset from the CDN and park it in storage."""
    store = ctx.require_storage()

    async with ctx.sessionmaker() as session:
        row = (
            await session.execute(
                # shard and played_at are part of the storage key, not
                # decoration: the layout is telemetry/{shard}/{yyyy}/{mm}/...
                # and the retention scan narrows on that prefix.
                select(
                    Match.telemetry_url,
                    Match.telemetry_key,
                    Match.shard,
                    Match.played_at,
                ).where(Match.match_id == match_id)
            )
        ).one_or_none()

    if row is None:
        raise MissingMatchError(f"no match row for {match_id}; run fetch_match first")

    telemetry_url, existing_key, shard, played_at = row
    if existing_key and await store.exists(existing_key):
        # Resumable: a crash between the upload and the DB write, or a plain
        # re-run, must not re-download 20 MB.
        log.debug("telemetry.already_stored", match_id=match_id, key=existing_key)
        await _queue_parse(ctx, match_id)
        return

    if not telemetry_url:
        raise MissingMatchError(f"match {match_id} has no telemetry URL")

    # The CDN is unauthenticated and unlimited; the client must not attach the
    # Authorization header here.
    blob = await ctx.api.download_telemetry(telemetry_url)
    if not blob.startswith(_GZIP_MAGIC):
        # The client may or may not have transparently decoded Content-Encoding
        # (aiter_bytes does, aiter_raw does not). Normalise on the magic number
        # so what lands in storage is always a real .gz, whichever it did.
        blob = await asyncio.to_thread(gzip.compress, blob, 6)

    key = store.key_for(shard, match_id, played_at)
    size = await store.put(key, blob)

    async with ctx.sessionmaker() as session, session.begin():
        await session.execute(
            update(Match)
            .where(Match.match_id == match_id)
            .values(telemetry_key=key, telemetry_bytes=size, telemetry_fetched_at=utcnow())
        )
        await enqueue(
            session,
            JOB_PARSE_TELEMETRY,
            {"match_id": match_id},
            key=dedupe_key(JOB_PARSE_TELEMETRY, match_id),
        )

    log.info("telemetry.stored", match_id=match_id, key=key, bytes=size)


async def _queue_parse(ctx: IngestContext, match_id: str) -> None:
    async with ctx.sessionmaker() as session, session.begin():
        await enqueue(
            session,
            JOB_PARSE_TELEMETRY,
            {"match_id": match_id},
            key=dedupe_key(JOB_PARSE_TELEMETRY, match_id),
        )


# ---------------------------------------------------------------------------
# parse_telemetry
# ---------------------------------------------------------------------------
async def parse_telemetry(ctx: IngestContext, match_id: str) -> None:
    """Parse stored raw telemetry into the replay bundle, kills and heatmap.

    Reads from object storage rather than the network: bumping
    `PARSER_VERSION` requeues every match and re-derives everything with no
    re-download, which is the entire reason raw telemetry is archived.
    """
    from pubg_dashboard.ingest.persist import persist_parse_result
    from pubg_dashboard.storage.base import replay_key as replay_key_for
    from pubg_dashboard.storage.factory import get_storage
    from pubg_dashboard.telemetry.bundle import read_heat_ledger
    from pubg_dashboard.telemetry.parse import parse_telemetry as run_parser

    storage = get_storage()

    async with ctx.sessionmaker() as session:
        row = (
            await session.execute(
                select(
                    Match.telemetry_key,
                    Match.shard,
                    Match.game_mode,
                    Match.match_type,
                    Match.map_name,
                    Match.played_at,
                    Match.telemetry_parsed_at,
                    Match.heat_ledger_key,
                ).where(Match.match_id == match_id)
            )
        ).one_or_none()

    if row is None:
        raise MissingMatchError(f"no match row for {match_id}")
    key, shard, game_mode, match_type, map_name, played_at, parsed_at, ledger_key = row
    if not key:
        raise MissingMatchError(
            f"{match_id} has no stored telemetry; run fetch_telemetry first"
        )

    raw = await storage.get(key)
    result = await asyncio.to_thread(
        run_parser,
        raw,
        match_id=match_id,
        shard=shard,
        game_mode=game_mode,
        match_type=match_type,
        played_at=played_at,
    )

    if result.unknown_events:
        # Never fatal — LogSpecialZoneInCharacters is in no documentation at
        # all — but a new event type should surface rather than vanish.
        log.info("telemetry.unknown_events", match_id=match_id, **result.unknown_events)

    # Subtract this match's previous heatmap contribution before adding the
    # new one, or a reparse double-counts every bin it touches.
    previous = None
    if ledger_key and await storage.exists(ledger_key):
        previous = read_heat_ledger(await storage.get(ledger_key))

    bundle_key = replay_key_for(result.parser_version, match_id)
    ledger_out = f"heat/v{result.parser_version}/{match_id}.msgpack.gz"
    await storage.put(bundle_key, result.bundle)
    await storage.put(ledger_out, result.heat_ledger)

    async with ctx.sessionmaker() as session, session.begin():
        await persist_parse_result(
            session,
            result,
            replay_key=bundle_key,
            heat_ledger_key=ledger_out,
            previous_ledger=previous,
            was_parsed=parsed_at is not None,
            map_name=map_name,
            match_type=match_type,
            day=played_at.astimezone(dt.UTC).date(),
        )

    log.info(
        "telemetry.parsed",
        match_id=match_id,
        kills=len(result.kill_rows),
        bins=len(result.heatmap_rows),
        replay_bytes=len(result.bundle),
    )


# ---------------------------------------------------------------------------
# backfill_player
# ---------------------------------------------------------------------------
async def backfill_player(ctx: IngestContext, account_id: str) -> None:
    """Queue a fetch for every match in a newly added player's recent history.

    Looked up by account id, not name: ids survive renames, and a name lookup
    404s the whole request if it is even slightly off.
    """
    payload = await ctx.api.get_players_by_ids([account_id])
    refs = parse_players_payload(payload)
    ref = next((item for item in refs if item.account_id == account_id), None)
    if ref is None:
        log.warning("backfill.player_not_found", account_id=account_id)
        return

    async with ctx.sessionmaker() as session, session.begin():
        if ref.name:
            # UPDATE, never INSERT: player CRUD owns `tracked`, and creating the
            # row here would create it untracked.
            await session.execute(
                update(Player).where(Player.account_id == account_id).values(name=ref.name)
            )
        # Skip matches we already hold: dedupe_key only suppresses *live* jobs,
        # so re-enqueueing an ingested match would re-fetch it for nothing.
        new_ids = await unknown_match_ids(session, ref.match_ids)
        queued = await enqueue_match_fetches(session, new_ids)

    log.info(
        "backfill.queued",
        account_id=account_id,
        available=len(ref.match_ids),
        queued=queued,
    )


# ---------------------------------------------------------------------------
# Worker registration
# ---------------------------------------------------------------------------
def _require(payload: Any, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"job payload is missing {field!r}: {payload!r}")
    return value


def build_handlers(ctx: IngestContext) -> dict[str, Handler]:
    """Bind the context into worker-shaped `async (job) -> None` callables."""

    async def _fetch_match(job: JobLike) -> None:
        await fetch_match(ctx, _require(job.payload, "match_id"))

    async def _fetch_telemetry(job: JobLike) -> None:
        await fetch_telemetry(ctx, _require(job.payload, "match_id"))

    async def _parse_telemetry(job: JobLike) -> None:
        await parse_telemetry(ctx, _require(job.payload, "match_id"))

    async def _backfill_player(job: JobLike) -> None:
        await backfill_player(ctx, _require(job.payload, "account_id"))

    return {
        JOB_FETCH_MATCH: _fetch_match,
        JOB_FETCH_TELEMETRY: _fetch_telemetry,
        JOB_PARSE_TELEMETRY: _parse_telemetry,
        JOB_BACKFILL_PLAYER: _backfill_player,
    }


def register_handlers(registry: MutableMapping[str, Handler], ctx: IngestContext) -> None:
    """Install the ingest handlers into the worker's handler registry."""
    registry.update(build_handlers(ctx))
