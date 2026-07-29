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

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from pubg_dashboard.api.deps import career_filter
from pubg_dashboard.api.schemas import (
    BaselineMetric,
    MatchStrategyRow,
    MatchZonePlay,
    SquadMatchRow,
    SquadPlayerCohesion,
    StrategyBaseline,
    StrategyMatchRow,
    ZonePhaseRate,
    ZonePlayRow,
    ZonePlaySummary,
)
from pubg_dashboard.db.models import Match, Participant, Player, StrategyMetric, ZonePlay
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


@router.get("/strategy/baseline", response_model=StrategyBaseline)
async def strategy_baseline(
    session: SessionDep,
    place_max: Annotated[int | None, Query(alias="placeMax", ge=1, le=100)] = None,
) -> StrategyBaseline:
    """What the rest of the lobby does — the comparison the page never had.

    `strategy_metrics` already holds a row per participant, opponents included,
    because the parser walks the whole match regardless. Every other endpoint
    here filters to tracked players, so this data has been sitting unused.

    Three exclusions, each of which changes the answer:

    * **Bots.** 19% of participants. They never rotate, never loot properly and
      never contest a drop, so including them flatters every human against a
      lobby that does not exist.
    * **Tracked players.** Otherwise the squad is compared partly against
      itself.
    * **Non-career match types**, via the same `career_filter` the stats use,
      so this and the player's own rows are drawn from the same population.

    `placeMax` narrows to finishers at or above a placement, which is what
    turns the baseline from "what everyone does" into "what the people who beat
    us do".

    Quantiles are computed per metric with `percentile_cont`, and **`n` is
    per metric too** — every column has a genuine "not measurable" case, and
    `teammate_dist_avg_cm` is NULL for an entire solo lobby. One shared row
    count would overstate all of them.
    """
    where = [
        Participant.is_bot.is_(False),
        # `tracked = false` is not the same question: `players` holds a row per
        # human opponent too, so the anti-join is against tracked players
        # specifically, not against the absence of a players row.
        Participant.account_id.not_in(select(Player.account_id).where(Player.tracked)),
    ]
    if place_max is not None:
        where.append(Participant.win_place <= place_max)

    cols = []
    for field in _METRIC_FIELDS:
        col = getattr(StrategyMetric, field)
        for q in (0.25, 0.5, 0.75):
            cols.append(func.percentile_cont(q).within_group(col.asc()))
        # count() of a nullable column counts non-NULLs, which is exactly the
        # question here — but it is spelled explicitly so nobody reads it as
        # the row count.
        cols.append(func.count(col))

    stmt = (
        select(func.count(func.distinct(Participant.match_id)), *cols)
        .select_from(StrategyMetric)
        .join(
            Participant,
            (Participant.match_id == StrategyMetric.match_id)
            & (Participant.account_id == StrategyMetric.account_id),
        )
        .join(Match, Match.match_id == StrategyMetric.match_id)
        .where(career_filter(), *where)
    )
    row = (await session.execute(stmt)).one()

    matches = int(row[0] or 0)
    out: list[BaselineMetric] = []
    for i, field in enumerate(_METRIC_FIELDS):
        p25, median, p75, n = row[1 + i * 4 : 5 + i * 4]
        out.append(
            BaselineMetric(
                metric=field,
                p25=None if p25 is None else float(p25),
                median=None if median is None else float(median),
                p75=None if p75 is None else float(p75),
                n=int(n or 0),
            )
        )
    return StrategyBaseline(metrics=out, matches=matches, place_max=place_max)


# ---------------------------------------------------------------------------
# circle discipline (parser v15)
# ---------------------------------------------------------------------------
def _zone_rate_cols() -> list[Any]:
    """Per-phase aggregates, counted separately per instant.

    `count(col)` on a nullable boolean counts non-NULLs, which is exactly the
    denominator wanted here — but it is spelled with an explicit FILTER so
    nobody reads it as the row count. `count()` of a non-nullable column
    proves nothing; that lesson cost this repo an entire accuracy feature.
    """
    return [
        func.count().filter(ZonePlay.in_circle_at_announce.is_(True)),
        func.count().filter(ZonePlay.in_circle_at_announce.is_not(None)),
        func.count().filter(ZonePlay.in_circle_at_close.is_(True)),
        func.count().filter(ZonePlay.in_circle_at_close.is_not(None)),
        func.percentile_cont(0.5).within_group(ZonePlay.dist_to_white_edge_cm.asc()),
    ]


def _zone_rows(rows: Sequence[Any]) -> list[ZonePhaseRate]:
    return [
        ZonePhaseRate(
            phase=int(phase),
            announce_in=int(a_in or 0),
            announce_n=int(a_n or 0),
            close_in=int(c_in or 0),
            close_n=int(c_n or 0),
            median_edge_m=None if edge is None else float(edge) / 100.0,
        )
        for phase, a_in, a_n, c_in, c_n, edge in rows
    ]


@router.get("/strategy/zone-play", response_model=ZonePlaySummary)
async def zone_play_summary(
    session: SessionDep,
    place_max: Annotated[int | None, Query(alias="placeMax", ge=1, le=100)] = None,
) -> ZonePlaySummary:
    """Were we inside the next circle, phase by phase — and was the lobby?

    Straight from `LogPhaseChange.playersInWhiteCircle`, so "inside" needs no
    geometry and carries no threshold. The two instants per phase are the
    white-circle **announcement** and the moment the blue **starts closing**;
    the second is the rotation deadline.

    **Only rows where the player was alive at the close count.** A dead player
    is not outside the circle, they are out of the match, and including them
    would make late-phase discipline look worse the more the squad lost.
    """
    tracked = select(Player.account_id).where(Player.tracked).scalar_subquery()
    career = select(Match.match_id).where(career_filter()).scalar_subquery()

    base = (
        select(ZonePlay.phase, *_zone_rate_cols())
        .join(
            Participant,
            (Participant.match_id == ZonePlay.match_id)
            & (Participant.account_id == ZonePlay.account_id),
        )
        .where(
            ZonePlay.match_id.in_(career),
            ZonePlay.alive_at_close.is_(True),
        )
        .group_by(ZonePlay.phase)
        .order_by(ZonePlay.phase)
    )

    squad = (await session.execute(base.where(ZonePlay.account_id.in_(tracked)))).all()

    lobby_where = [
        Participant.is_bot.is_(False),
        ZonePlay.account_id.not_in(tracked),
    ]
    if place_max is not None:
        lobby_where.append(Participant.win_place <= place_max)
    lobby = (await session.execute(base.where(*lobby_where))).all()

    matches = (
        await session.execute(
            select(func.count(func.distinct(ZonePlay.match_id))).where(
                ZonePlay.match_id.in_(career), ZonePlay.account_id.in_(tracked)
            )
        )
    ).scalar_one()

    return ZonePlaySummary(
        squad=_zone_rows(squad),
        lobby=_zone_rows(lobby),
        matches=int(matches or 0),
        place_max=place_max,
    )


@router.get("/matches/{match_id}/zone-play", response_model=MatchZonePlay)
async def match_zone_play(session: SessionDep, match_id: str) -> MatchZonePlay:
    """Per-phase rows for the tracked players in one match, keyed by name.

    An empty `players` is a real answer — a match parsed before v15 has no
    rows — and the frontend must not dress it up as an error.

    `max_phase` is taken over **every** participant, not just the tracked
    ones. A squad wiped in phase 1 has rows for phase 1 only, and using their
    own maximum would render the match as one phase long — making "we died
    early" indistinguishable from "the match was short".
    """
    max_phase = (
        await session.execute(
            select(func.max(ZonePlay.phase)).where(ZonePlay.match_id == match_id)
        )
    ).scalar_one_or_none()
    rows = (
        await session.execute(
            select(Participant.name, ZonePlay)
            .join(
                Participant,
                (Participant.match_id == ZonePlay.match_id)
                & (Participant.account_id == ZonePlay.account_id),
            )
            .join(Player, Player.account_id == ZonePlay.account_id)
            .where(ZonePlay.match_id == match_id, Player.tracked)
            .order_by(Participant.name, ZonePlay.phase)
        )
    ).all()

    players: dict[str, list[ZonePlayRow]] = {}
    for name, zp in rows:
        players.setdefault(name, []).append(
            ZonePlayRow(
                phase=zp.phase,
                announce_t_s=zp.announce_t_s,
                close_t_s=zp.close_t_s,
                in_circle_at_announce=zp.in_circle_at_announce,
                in_circle_at_close=zp.in_circle_at_close,
                dist_to_white_edge_cm=zp.dist_to_white_edge_cm,
                white_r_cm=zp.white_r_cm,
                alive_at_close=zp.alive_at_close,
                in_vehicle_at_close=zp.in_vehicle_at_close,
                sample_lag_ms=zp.sample_lag_ms,
            )
        )
    return MatchZonePlay(max_phase=int(max_phase or 0), players=players)
