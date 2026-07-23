"""Strategy insights: per-match behavioral metrics, ready to contrast by placement.

The endpoints return **rows, not conclusions**. With a few dozen official matches per
tracked player, the honest analysis is a best-N vs worst-N contrast, and that
lives in a pure frontend function (`lib/strategy.ts`) where it is hermetically
testable — the server's job is a faithful join.

Bots never appear here: the metric rows exist for them (an opponent baseline is
free once computed), but every endpoint joins through `players`/tracked or
filters `is_bot` explicitly.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import desc, func, select

from pubg_dashboard.api.deps import career_filter
from pubg_dashboard.api.schemas import (
    MatchStrategyRow,
    SquadMatchRow,
    SquadPlayerCohesion,
    StrategyMatchRow,
)
from pubg_dashboard.db.models import Match, Participant, Player, StrategyMetric
from pubg_dashboard.db.session import SessionDep

router = APIRouter(tags=["strategy"])

_METRIC_FIELDS = (
    "blue_s",
    "blue_damage",
    "rotate_lag_s",
    "teammate_dist_avg_cm",
    "teammate_near_pct",
    "hot_drop_n",
    "first_engage_s",
    "dmg_dealt_early",
    "dmg_taken_early",
    "first_weapon_s",
    "early_pickups_n",
)


def _metrics(sm: StrategyMetric) -> dict[str, object]:
    return {f: getattr(sm, f) for f in _METRIC_FIELDS}


@router.get("/players/{account_id}/strategy", response_model=list[StrategyMatchRow])
async def player_strategy(session: SessionDep, account_id: str) -> list[StrategyMatchRow]:
    """Per-official-match metric rows for one player, newest first.

    Inner join on `strategy_metrics`: a match parsed before parser v7 has no
    row and cannot contribute to a contrast — after a reparse it appears.
    """
    stmt = (
        select(Participant, Match, StrategyMetric)
        .join(Match, Match.match_id == Participant.match_id)
        .join(
            StrategyMetric,
            (StrategyMetric.match_id == Participant.match_id)
            & (StrategyMetric.account_id == Participant.account_id),
        )
        .where(Participant.account_id == account_id, career_filter())
        .order_by(desc(Match.played_at))
    )
    rows = (await session.execute(stmt)).all()
    return [
        StrategyMatchRow(
            match_id=m.match_id,
            played_at=m.played_at,
            map_name=m.map_name,
            game_mode=m.game_mode,
            team_size=m.team_size,
            win_place=p.win_place,
            time_survived=p.time_survived,
            # Human kills are the headline everywhere in this app; the raw
            # count is the fallback for anything parsed before the column.
            kills=p.kills_human if p.kills_human is not None else p.kills,
            damage_dealt=p.damage_dealt,
            ride_distance=p.ride_distance,
            walk_distance=p.walk_distance,
            **_metrics(sm),
        )
        for p, m, sm in rows
    ]


@router.get("/strategy/squad", response_model=list[SquadMatchRow])
async def squad_strategy(session: SessionDep) -> list[SquadMatchRow]:
    """Matches where at least two tracked players shared a team.

    This is the only place teammate-distance metrics mean "our squad" rather
    than "whoever PUBG teamed me with", so it is grouped by match rather than
    by player.
    """
    pair = (
        select(Participant.match_id, Participant.team_id)
        .join(Player, Player.account_id == Participant.account_id)
        .where(Player.tracked)
        .group_by(Participant.match_id, Participant.team_id)
        .having(func.count() >= 2)
        .subquery()
    )
    stmt = (
        select(Participant, Match, StrategyMetric)
        .join(
            pair,
            (pair.c.match_id == Participant.match_id)
            & (pair.c.team_id == Participant.team_id),
        )
        .join(Match, Match.match_id == Participant.match_id)
        .join(
            StrategyMetric,
            (StrategyMetric.match_id == Participant.match_id)
            & (StrategyMetric.account_id == Participant.account_id),
        )
        .join(Player, Player.account_id == Participant.account_id)
        .where(Player.tracked, career_filter())
        .order_by(desc(Match.played_at))
    )
    rows = (await session.execute(stmt)).all()

    by_match: dict[str, SquadMatchRow] = {}
    for p, m, sm in rows:
        entry = by_match.get(m.match_id)
        if entry is None:
            entry = by_match[m.match_id] = SquadMatchRow(
                match_id=m.match_id,
                played_at=m.played_at,
                map_name=m.map_name,
                game_mode=m.game_mode,
                win_place=p.win_place,
                players=[],
            )
        entry.players.append(
            SquadPlayerCohesion(account_id=p.account_id, name=p.name, **_metrics(sm))
        )
    return list(by_match.values())


@router.get("/matches/{match_id}/strategy", response_model=list[MatchStrategyRow])
async def match_strategy(session: SessionDep, match_id: str) -> list[MatchStrategyRow]:
    """Metric rows for the tracked players in one match — the debrief panel.

    An empty list is a real answer (match not yet reparsed under v7, or no
    tracked player in it); the frontend must not dress it up as an error.
    """
    stmt = (
        select(Participant, StrategyMetric)
        .join(
            StrategyMetric,
            (StrategyMetric.match_id == Participant.match_id)
            & (StrategyMetric.account_id == Participant.account_id),
        )
        .join(Player, Player.account_id == Participant.account_id)
        .where(Participant.match_id == match_id, Player.tracked)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MatchStrategyRow(account_id=p.account_id, name=p.name, **_metrics(sm))
        for p, sm in rows
    ]
