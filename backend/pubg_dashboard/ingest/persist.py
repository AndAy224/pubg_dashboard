"""Writing a `ParseResult` to Postgres and object storage.

The whole point of this module is **idempotence**. `parse_telemetry` is not a
one-shot job: bumping `PARSER_VERSION` requeues every match so improvements
apply to the whole archive without re-downloading a byte. So every write here
has to be safe to repeat, and the heatmap is the one that is not naturally so —
bins accumulate, and a second parse of the same match would add its counts on
top of the first.

That is what `heat_ledger_key` is for. Each parse records exactly what it added;
a reparse subtracts the previous ledger before adding the new figures. If the
ledger is missing for a match that has already been parsed, this **refuses to
reparse** rather than silently inflating every bin — a heatmap that is quietly
2x is indistinguishable from a popular drop spot.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import HeatmapBin, KillEvent, Match, Participant, utcnow
from pubg_dashboard.telemetry.parse import ParseResult

log = structlog.get_logger(__name__)

__all__ = ["ReparseWithoutLedgerError", "persist_parse_result"]

_CHUNK = 500


class ReparseWithoutLedgerError(RuntimeError):
    """A parsed match has no heat ledger, so its bins cannot be reversed."""


def _chunks(rows: list[dict[str, Any]], size: int = _CHUNK):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def persist_parse_result(
    session: AsyncSession,
    result: ParseResult,
    *,
    replay_key: str,
    heat_ledger_key: str,
    previous_ledger: list[tuple[str, str, str, int, int, int]] | None,
    was_parsed: bool,
    map_name: str,
    match_type: str,
    day: dt.date,
) -> None:
    """Persist one parse. Safe to run repeatedly for the same match."""
    match_id = result.match_id

    if was_parsed and previous_ledger is None:
        raise ReparseWithoutLedgerError(
            f"{match_id} is already parsed but has no heat ledger; refusing to "
            "reparse because its heatmap contribution cannot be subtracted"
        )

    # --- kill_events: delete-then-insert ----------------------------------
    # `seq` is only stable within one parser version, so a changed parser can
    # produce fewer rows than last time. Upserting would leave the surplus
    # behind as phantom kills.
    await session.execute(delete(KillEvent).where(KillEvent.match_id == match_id))
    for chunk in _chunks(result.kill_rows):
        await session.execute(pg_insert(KillEvent).values(chunk))

    # --- heatmap bins: reverse the old contribution, then add the new ------
    if previous_ledger:
        # `match_type` is not in the ledger because every bin a single match
        # contributes carries that match's type — it is a constant, not a
        # dimension, so it is reapplied here rather than stored 400k times.
        await _apply_heat(
            session,
            [
                {
                    "map_name": map_name, "kind": kind, "account_id": account,
                    "game_mode": mode, "match_type": match_type, "day": day,
                    "grid_x": gx, "grid_y": gy, "count": -count,
                }
                for kind, account, mode, gx, gy, count in previous_ledger
            ],
        )
    await _apply_heat(session, result.heatmap_rows)

    # A reversal can leave bins at exactly zero. They are not wrong, but they
    # accumulate across reparses and make every heatmap read scan dead rows.
    await session.execute(delete(HeatmapBin).where(HeatmapBin.count <= 0))

    # --- participants: telemetry-derived columns --------------------------
    for row in result.participant_updates:
        await session.execute(
            update(Participant)
            .where(
                Participant.match_id == match_id,
                Participant.account_id == row["account_id"],
            )
            .values(
                kills_human=row["kills_human"],
                knocks_human=row["knocks_human"],
                landing_x=row["landing_x"],
                landing_y=row["landing_y"],
                death_x=row["death_x"],
                death_y=row["death_y"],
                died_at_s=row["died_at_s"],
                killer_account_id=row["killer_account_id"],
                death_weapon=row["death_weapon"],
                shots_fired=row["shots_fired"],
                shots_hit=row["shots_hit"],
                # Telemetry is authoritative for bot-ness: `character.type ==
                # 'user_ai'` also catches a bot PUBG handed a real-looking id,
                # which the `ai.` prefix fallback would miss.
                is_bot=row["is_bot"],
            )
        )

    # --- match row --------------------------------------------------------
    meta = result.meta
    await session.execute(
        update(Match)
        .where(Match.match_id == match_id)
        .values(
            telemetry_parsed_at=utcnow(),
            parser_version=result.parser_version,
            parse_error=None,
            replay_key=replay_key,
            replay_bytes=len(result.bundle),
            heat_ledger_key=heat_ledger_key,
            telemetry_t0=dt.datetime.fromtimestamp(meta.t0_ms / 1000.0, dt.UTC),
            team_size=meta.team_size or None,
            weather_id=meta.weather_id or None,
            camera_view=meta.camera_view or None,
            num_start_players=len(result.players),
            num_start_teams=len({p.team_id for p in result.players}),
            bot_count=sum(1 for p in result.players if p.is_bot),
        )
    )

    log.info(
        "telemetry.persisted",
        match_id=match_id,
        kills=len(result.kill_rows),
        bins=len(result.heatmap_rows),
        reversed_bins=len(previous_ledger or ()),
        replay_bytes=len(result.bundle),
    )


async def _apply_heat(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """`count = count + EXCLUDED.count`, in chunks.

    The primary key uses `''` sentinels rather than NULLs precisely so this
    conflict target fires. With nullable columns `NULL != NULL` would make the
    global rows never conflict, and every parse would append a duplicate set.
    """
    for chunk in _chunks(rows):
        stmt = pg_insert(HeatmapBin).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                # Every primary-key column, in order. Omitting one makes
                # Postgres fail to infer the constraint rather than silently
                # matching a different one.
                index_elements=[
                    HeatmapBin.map_name, HeatmapBin.kind, HeatmapBin.account_id,
                    HeatmapBin.game_mode, HeatmapBin.match_type, HeatmapBin.day,
                    HeatmapBin.grid_x, HeatmapBin.grid_y,
                ],
                set_={"count": HeatmapBin.count + stmt.excluded.count},
            )
        )
