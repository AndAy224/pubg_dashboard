"""Player cards, career stats, match history, weapons."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Float, and_, cast, desc, func, select

from pubg_dashboard.api.deps import career_filter, kills_column
from pubg_dashboard.api.schemas import (
    MatchSummary,
    PlayerCard,
    PlayerStats,
    TimeseriesPoint,
    WeaponStat,
)
from pubg_dashboard.db.models import KillEvent, Match, Participant, Player, Roster
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.maps import display_name

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=list[PlayerCard])
async def list_players(
    session: SessionDep,
    tracked: Annotated[bool | None, Query(description="Filter by tracked flag.")] = None,
    q: Annotated[str | None, Query(description="Case-insensitive name search.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PlayerCard]:
    played = (
        select(
            Participant.account_id.label("account_id"),
            func.count().label("matches"),
            func.max(Match.played_at).label("last_seen"),
        )
        .join(Match, Match.match_id == Participant.match_id)
        .group_by(Participant.account_id)
        .subquery()
    )
    stmt = (
        select(Player, played.c.matches, played.c.last_seen)
        .outerjoin(played, played.c.account_id == Player.account_id)
        .limit(limit)
    )
    if tracked is not None:
        stmt = stmt.where(Player.tracked.is_(tracked))
    if q:
        # Matches ix_players_name_lower.
        stmt = stmt.where(func.lower(Player.name).like(f"%{q.lower()}%"))
    stmt = stmt.order_by(desc(Player.tracked), desc(func.coalesce(played.c.matches, 0)))

    return [
        PlayerCard(
            account_id=p.account_id,
            name=p.name,
            shard=p.shard,
            tracked=p.tracked,
            matches=n or 0,
            last_seen=last,
            last_polled_at=p.last_polled_at,
            consecutive_poll_failures=p.consecutive_poll_failures,
        )
        for p, n, last in (await session.execute(stmt)).all()
    ]


@router.get("/{account_id}/stats", response_model=PlayerStats)
async def player_stats(
    session: SessionDep,
    account_id: str,
    include_bots: Annotated[bool, Query(alias="includeBots")] = False,
    since: Annotated[dt.datetime | None, Query()] = None,
    until: Annotated[dt.datetime | None, Query()] = None,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
) -> PlayerStats:
    """Career aggregate over `official` matches only.

    Bots are excluded from kills by default. They are ~19% of all kills and
    just over half of the tracked players' — reporting raw `kills` overstates
    one tracked player's K/D by 57%.
    """
    name = await session.scalar(select(Player.name).where(Player.account_id == account_id))

    where = [Participant.account_id == account_id, career_filter()]
    if since:
        where.append(Match.played_at >= since)
    if until:
        where.append(Match.played_at <= until)
    if game_mode:
        where.append(Match.game_mode == game_mode)

    row = (
        await session.execute(
            select(
                func.count().label("matches"),
                func.count().filter(Participant.win_place == 1).label("wins"),
                func.count().filter(Participant.win_place <= 10).label("top10"),
                # Both aggregated unconditionally. `include_bots` chooses
                # which the UI leads with; it must not change what either
                # number *means*, or this response quietly disagrees with the
                # match list where `kills` is the raw API stat.
                func.coalesce(func.sum(Participant.kills), 0).label("kills_raw"),
                func.coalesce(func.sum(kills_column(False)), 0).label("kills_human"),
                func.coalesce(func.sum(Participant.dbnos), 0).label("knocks"),
                func.coalesce(func.sum(Participant.assists), 0).label("assists"),
                func.coalesce(func.sum(Participant.headshot_kills), 0).label("hs"),
                func.coalesce(func.sum(Participant.revives), 0).label("revives"),
                func.coalesce(func.sum(Participant.damage_dealt), 0.0).label("damage"),
                func.coalesce(func.max(Participant.longest_kill), 0.0).label("longest"),
                func.coalesce(func.avg(cast(Participant.win_place, Float)), 0.0).label("avg_place"),
                func.coalesce(func.sum(Participant.time_survived), 0.0).label("survived"),
                func.coalesce(func.sum(Participant.walk_distance), 0.0).label("walk"),
                func.coalesce(func.sum(Participant.ride_distance), 0.0).label("ride"),
            )
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(and_(*where))
        )
    ).one()

    n = row.matches or 0
    if n == 0:
        raise HTTPException(404, f"no career matches for {account_id}")

    return PlayerStats(
        account_id=account_id,
        name=name or account_id,
        matches=n,
        wins=row.wins,
        top10=row.top10,
        kills=int(row.kills_raw),
        kills_human=int(row.kills_human),
        knocks=int(row.knocks),
        assists=int(row.assists),
        headshot_kills=int(row.hs),
        revives=int(row.revives),
        damage_dealt=float(row.damage),
        longest_kill_m=float(row.longest),
        avg_damage=float(row.damage) / n,
        avg_place=float(row.avg_place),
        kd=float(row.kills_raw) / n,
        kd_human=float(row.kills_human) / n,
        win_rate=row.wins / n,
        time_survived_s=float(row.survived),
        walk_distance_m=float(row.walk),
        ride_distance_m=float(row.ride),
        include_bots=include_bots,
    )


@router.get("/{account_id}/matches", response_model=list[MatchSummary])
async def player_matches(
    session: SessionDep,
    account_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    before: Annotated[dt.datetime | None, Query(description="Keyset cursor.")] = None,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
    map_name: Annotated[str | None, Query(alias="mapName")] = None,
    career_only: Annotated[bool, Query(alias="careerOnly")] = False,
) -> list[MatchSummary]:
    """Newest first.

    Paginated by keyset on `played_at`, not OFFSET: new matches arrive at the
    head constantly, and an offset page would skip or repeat rows as they do.
    """
    where = [Participant.account_id == account_id]
    if before:
        where.append(Match.played_at < before)
    if game_mode:
        where.append(Match.game_mode == game_mode)
    if map_name:
        where.append(Match.map_name == map_name)
    if career_only:
        where.append(career_filter())

    rows = (
        await session.execute(
            select(Participant, Match, Roster.won)
            .join(Match, Match.match_id == Participant.match_id)
            .outerjoin(
                Roster,
                and_(
                    Roster.match_id == Participant.match_id,
                    Roster.team_id == Participant.team_id,
                ),
            )
            .where(and_(*where))
            .order_by(Match.played_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        MatchSummary(
            match_id=m.match_id,
            played_at=m.played_at,
            map_name=m.map_name,
            map_display=display_name(m.map_name),
            game_mode=m.game_mode,
            match_type=m.match_type,
            duration_s=m.duration_s,
            team_id=p.team_id,
            win_place=p.win_place,
            roster_won=bool(won),
            kills=p.kills,
            kills_human=p.kills_human,
            assists=p.assists,
            damage_dealt=p.damage_dealt,
            time_survived=p.time_survived,
            death_type=p.death_type,
            has_replay=m.replay_key is not None,
        )
        for p, m, won in rows
    ]


@router.get("/{account_id}/weapons", response_model=list[WeaponStat])
async def player_weapons(
    session: SessionDep,
    account_id: str,
    include_bots: Annotated[bool, Query(alias="includeBots")] = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[WeaponStat]:
    """Weapon breakdown from `kill_events`.

    `distance_cm = -1` is a "not applicable" sentinel (8.6% of kills), so it is
    filtered out of both the maximum and the average — otherwise every melee
    and vehicle kill drags the averages toward -1 and the longest-kill figure
    is meaningless.
    """
    where = [
        KillEvent.killer_account_id == account_id,
        KillEvent.weapon.is_not(None),
        KillEvent.is_suicide.is_(False),
        KillEvent.is_team_kill.is_(False),
    ]
    if not include_bots:
        where.append(KillEvent.victim_is_bot.is_(False))

    real_distance = and_(KillEvent.distance_cm.is_not(None), KillEvent.distance_cm > 0)
    rows = (
        await session.execute(
            select(
                KillEvent.weapon,
                func.count().label("kills"),
                func.count().filter(KillEvent.damage_reason == "HeadShot").label("hs"),
                func.coalesce(func.max(KillEvent.distance_cm).filter(real_distance), 0.0),
                func.coalesce(func.avg(KillEvent.distance_cm).filter(real_distance), 0.0),
            )
            .where(and_(*where))
            .group_by(KillEvent.weapon)
            .order_by(desc("kills"))
            .limit(limit)
        )
    ).all()

    return [
        WeaponStat(
            weapon=weapon,
            kills=kills,
            headshots=hs,
            longest_m=float(longest) / 100.0,
            avg_distance_m=float(avg) / 100.0,
        )
        for weapon, kills, hs, longest, avg in rows
    ]


@router.get("/{account_id}/timeseries", response_model=list[TimeseriesPoint])
async def player_timeseries(
    session: SessionDep,
    account_id: str,
    metric: Annotated[str, Query(pattern="^(kills|damage|winPlace|survival)$")] = "kills",
    include_bots: Annotated[bool, Query(alias="includeBots")] = False,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[TimeseriesPoint]:
    column = {
        "kills": kills_column(include_bots),
        "damage": Participant.damage_dealt,
        "winPlace": Participant.win_place,
        "survival": Participant.time_survived,
    }[metric]
    # Average for placement (a mean rank is meaningful); sum for the rest.
    agg = func.avg if metric == "winPlace" else func.sum

    day = func.date_trunc("day", Match.played_at)
    rows = (
        await session.execute(
            select(day.label("day"), func.count().label("n"), agg(column).label("value"))
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(
                Participant.account_id == account_id,
                career_filter(),
                Match.played_at >= dt.datetime.now(dt.UTC) - dt.timedelta(days=days),
            )
            .group_by(day)
            .order_by(day)
        )
    ).all()

    return [
        TimeseriesPoint(day=d.date(), matches=n, value=float(v or 0.0)) for d, n, v in rows
    ]
