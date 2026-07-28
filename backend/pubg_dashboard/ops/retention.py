"""Deleting things without corrupting the heatmap.

Two operations, and both are dangerous in the same specific way: `heatmap_bins`
has **no `match_id` column and no foreign key**. A match's contribution to the
heatmap is recorded only in its heat ledger in object storage, so removing the
row without first reversing the ledger leaves counts that nothing can ever
attribute or undo — and the inflation is invisible, because a heatmap that is
quietly too high looks exactly like a popular drop spot.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import HeatmapBin, Match, utcnow
from pubg_dashboard.ingest.persist import ReparseWithoutLedgerError, _apply_heat
from pubg_dashboard.storage.base import Storage
from pubg_dashboard.telemetry.bundle import PARSER_VERSION, read_heat_ledger

log = structlog.get_logger(__name__)

__all__ = ["PruneCandidate", "delete_match", "prune_telemetry"]


@dataclass(slots=True)
class PruneCandidate:
    match_id: str
    played_at: dt.datetime
    telemetry_key: str
    bytes_: int


async def delete_match(
    session: AsyncSession,
    storage: Storage,
    match_id: str,
    *,
    keep_telemetry: bool = False,
) -> None:
    """Remove a match and everything derived from it, heatmap included.

    **The order is the entire feature.** The heat ledger key lives on the match
    row, so it is read and applied *before* anything is deleted. Delete the row
    first and the ledger is orphaned in object storage with no way to find it,
    the bins stay permanently inflated, and a later re-ingest of the same match
    adds its contribution a second time.

    Refuses rather than guesses when a parsed match has no ledger — the same
    refusal `persist_parse_result` makes, for the same reason.
    """
    row = (
        await session.execute(
            select(
                Match.heat_ledger_key,
                Match.replay_key,
                Match.telemetry_key,
                Match.telemetry_parsed_at,
            ).where(Match.match_id == match_id)
        )
    ).one_or_none()
    if row is None:
        raise LookupError(f"no such match: {match_id}")
    ledger_key, replay_key, telemetry_key, parsed_at = row

    if parsed_at is not None:
        if not ledger_key:
            raise ReparseWithoutLedgerError(
                f"{match_id} is parsed but has no heat ledger; its heatmap "
                "contribution cannot be reversed, so it cannot be deleted safely"
            )
        ledger = read_heat_ledger(await storage.get(ledger_key))
        await _apply_heat(
            session,
            [
                {
                    "map_name": (await _map_name(session, match_id)),
                    "kind": kind,
                    "account_id": account,
                    "game_mode": mode,
                    "match_type": (await _match_type(session, match_id)),
                    "day": (await _day(session, match_id)),
                    "grid_x": gx,
                    "grid_y": gy,
                    "count": -count,
                }
                for kind, account, mode, gx, gy, count in ledger
            ],
        )
        await session.execute(delete(HeatmapBin).where(HeatmapBin.count <= 0))

    # Everything else cascades from the match row.
    await session.execute(delete(Match).where(Match.match_id == match_id))

    for key in (replay_key, ledger_key, None if keep_telemetry else telemetry_key):
        if key:
            await storage.delete(key)
    log.info("match.deleted", match_id=match_id, kept_telemetry=keep_telemetry)


async def _map_name(session: AsyncSession, match_id: str) -> str:
    return await session.scalar(select(Match.map_name).where(Match.match_id == match_id)) or ""


async def _match_type(session: AsyncSession, match_id: str) -> str:
    return await session.scalar(select(Match.match_type).where(Match.match_id == match_id)) or ""


async def _day(session: AsyncSession, match_id: str) -> dt.date:
    played = await session.scalar(select(Match.played_at).where(Match.match_id == match_id))
    return (played or utcnow()).astimezone(dt.UTC).date()


async def prune_telemetry(
    session: AsyncSession, retention_days: int
) -> list[PruneCandidate]:
    """Raw telemetry old enough to expire. **Returns candidates, deletes nothing.**

    `raw_telemetry_retention_days` has been in the config since the project
    started and nothing has ever read it. Zero means disabled, and that stays
    the default: raw telemetry is what makes a `PARSER_VERSION` bump able to
    re-derive the whole archive, and this session alone spent four of them.

    Two guards, and the second is the one that matters:

    * never a match that is not parsed at all — deleting its telemetry means it
      can never be parsed, and nothing would ever say so;
    * **never a match below the head parser version.** That match is going to
      be reparsed by the next bump, and pruning it means the reparse produces
      nothing, its heat ledger is subtracted, and its contribution vanishes
      from the heatmap without an error anywhere.
    """
    if retention_days <= 0:
        return []
    cutoff = utcnow() - dt.timedelta(days=retention_days)
    rows = (
        await session.execute(
            select(Match.match_id, Match.played_at, Match.telemetry_key, Match.telemetry_bytes)
            .where(
                Match.telemetry_key.is_not(None),
                Match.played_at < cutoff,
                Match.telemetry_parsed_at.is_not(None),
                Match.parser_version == PARSER_VERSION,
            )
            .order_by(Match.played_at)
        )
    ).all()
    return [
        PruneCandidate(match_id=m, played_at=p, telemetry_key=k, bytes_=int(b or 0))
        for m, p, k, b in rows
    ]
