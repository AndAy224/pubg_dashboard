"""Player cards, career stats, match history, weapons, trends."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Float, and_, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from pubg_dashboard.api.deps import career_filter, kills_column
from pubg_dashboard.api.schemas import (
    MatchSummary,
    Nemesis,
    PlacementBucket,
    PlayerCard,
    PlayerStats,
    TimeseriesPoint,
    WeaponStat,
)
from pubg_dashboard.db.models import KillEvent, Match, Participant, Player, Roster
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.maps import display_name

router = APIRouter(prefix="/players", tags=["players"])

#: Placement histogram buckets. The top one is a single value on purpose —
#: "#1" is the only result the game itself celebrates.
PLACEMENT_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("#1", 1, 1),
    ("2-5", 2, 5),
    ("6-10", 6, 10),
    ("11-25", 11, 25),
    ("26+", 26, None),
)


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


async def career_stats(
    session: AsyncSession,
    account_id: str,
    *,
    include_bots: bool = False,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    game_mode: str | None = None,
    map_name: str | None = None,
    name: str | None = None,
) -> PlayerStats | None:
    """Career aggregate over `official` matches only, or None if there are none.

    Bots are excluded from kills by default. They are ~19% of all kills and
    just over half of the tracked players' — reporting raw `kills` overstates
    one tracked player's K/D by 57%.
    """
    if name is None:
        name = await session.scalar(
            select(Player.name).where(Player.account_id == account_id)
        )

    where = [Participant.account_id == account_id, career_filter()]
    if since:
        where.append(Match.played_at >= since)
    if until:
        where.append(Match.played_at < until)
    if game_mode:
        where.append(Match.game_mode == game_mode)
    if map_name:
        where.append(Match.map_name == map_name)

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
                func.coalesce(func.sum(Participant.knocks_human), 0).label("knocks_human"),
                func.coalesce(func.sum(Participant.assists), 0).label("assists"),
                func.coalesce(func.sum(Participant.headshot_kills), 0).label("hs"),
                func.coalesce(func.sum(Participant.revives), 0).label("revives"),
                func.coalesce(func.sum(Participant.damage_dealt), 0.0).label("damage"),
                func.coalesce(func.max(Participant.longest_kill), 0.0).label("longest"),
                func.coalesce(func.avg(cast(Participant.win_place, Float)), 0.0).label(
                    "avg_place"
                ),
                func.coalesce(func.min(Participant.win_place), 0).label("best_place"),
                func.coalesce(func.sum(Participant.time_survived), 0.0).label("survived"),
                func.coalesce(func.sum(Participant.walk_distance), 0.0).label("walk"),
                func.coalesce(func.sum(Participant.ride_distance), 0.0).label("ride"),
                # Telemetry-derived. NULL on an unparsed match, so summed with
                # coalesce rather than assumed present.
                func.coalesce(func.sum(Participant.shots_fired), 0).label("fired"),
                func.coalesce(func.sum(Participant.shots_hit), 0).label("hit"),
                func.coalesce(func.sum(Participant.road_kills), 0).label("road"),
                func.coalesce(func.sum(Participant.vehicle_destroys), 0).label("vdest"),
                func.coalesce(func.sum(Participant.team_kills), 0).label("tk"),
            )
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(and_(*where))
        )
    ).one()

    n = row.matches or 0
    if n == 0:
        return None

    fired = int(row.fired)
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
        accuracy=(int(row.hit) / fired) if fired else 0.0,
        shots_fired=fired,
        shots_hit=int(row.hit),
        # Over raw kills: `headshot_kills` is the API's own figure and counts
        # bots, so dividing by kills_human would overstate the rate.
        headshot_rate=(int(row.hs) / int(row.kills_raw)) if row.kills_raw else 0.0,
        knocks_human=int(row.knocks_human),
        road_kills=int(row.road),
        vehicle_destroys=int(row.vdest),
        team_kills=int(row.tk),
        avg_survived_s=float(row.survived) / n,
        best_place=int(row.best_place),
    )


@router.get("/{account_id}/stats", response_model=PlayerStats)
async def player_stats(
    session: SessionDep,
    account_id: str,
    include_bots: Annotated[bool, Query(alias="includeBots")] = False,
    since: Annotated[dt.datetime | None, Query()] = None,
    until: Annotated[dt.datetime | None, Query()] = None,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
    map_name: Annotated[str | None, Query(alias="mapName")] = None,
) -> PlayerStats:
    stats = await career_stats(
        session,
        account_id,
        include_bots=include_bots,
        since=since,
        until=until,
        game_mode=game_mode,
        map_name=map_name,
    )
    if stats is None:
        raise HTTPException(404, f"no career matches for {account_id}")
    return stats


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

    The killer's name comes from a `participants` self-join — bots kill often
    and have no `players` row, so joining there would blank those deaths.
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

    killer = aliased(Participant, name="killer")
    rows = (
        await session.execute(
            select(Participant, Match, Roster.won, killer.name, killer.is_bot)
            .join(Match, Match.match_id == Participant.match_id)
            .outerjoin(
                Roster,
                and_(
                    Roster.match_id == Participant.match_id,
                    Roster.team_id == Participant.team_id,
                ),
            )
            .outerjoin(
                killer,
                and_(
                    killer.match_id == Participant.match_id,
                    killer.account_id == Participant.killer_account_id,
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
            knocks=p.dbnos,
            headshot_kills=p.headshot_kills,
            killed_by=killer_name,
            killed_by_is_bot=killer_is_bot,
            death_weapon=p.death_weapon,
            shots_fired=p.shots_fired,
            shots_hit=p.shots_hit,
            num_start_teams=m.num_start_teams,
        )
        for p, m, won, killer_name, killer_is_bot in rows
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


@router.get("/{account_id}/placements", response_model=list[PlacementBucket])
async def player_placements(
    session: SessionDep,
    account_id: str,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
) -> list[PlacementBucket]:
    """Placement distribution over career matches.

    Buckets are computed in one pass with FILTER rather than five queries.
    The tail bucket is open-ended: `win_place` has been observed above 100,
    so an upper bound would silently drop rows.
    """
    where = [Participant.account_id == account_id, career_filter()]
    if game_mode:
        where.append(Match.game_mode == game_mode)

    columns = [
        func.count()
        .filter(
            Participant.win_place >= lo
            if hi is None
            else and_(Participant.win_place >= lo, Participant.win_place <= hi)
        )
        .label(f"b{i}")
        for i, (_, lo, hi) in enumerate(PLACEMENT_BUCKETS)
    ]
    row = (
        await session.execute(
            select(*columns)
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(and_(*where))
        )
    ).one()

    return [
        PlacementBucket(label=label, lo=lo, hi=hi, matches=int(row[i]))
        for i, (label, lo, hi) in enumerate(PLACEMENT_BUCKETS)
    ]


@router.get("/{account_id}/nemeses", response_model=list[Nemesis])
async def player_nemeses(
    session: SessionDep,
    account_id: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[Nemesis]:
    """Humans who kill this player, and who this player kills.

    Bots are excluded on both sides and it is not a toggle: `ai.<n>` ids are
    match-scoped and recycled — `ai.322` alone is 14 unrelated bots — so
    grouping kills by a bot id would invent a single arch-nemesis out of
    dozens of unrelated opponents.

    Career match types only, so this agrees with the rest of the stats page.
    """
    deaths = (
        await session.execute(
            select(
                KillEvent.killer_account_id.label("acct"),
                func.count().label("n"),
                func.max(Match.played_at).label("last"),
            )
            .join(Match, Match.match_id == KillEvent.match_id)
            .where(
                KillEvent.victim_account_id == account_id,
                KillEvent.killer_account_id.is_not(None),
                KillEvent.killer_is_bot.is_(False),
                KillEvent.is_suicide.is_(False),
                career_filter(),
            )
            .group_by(KillEvent.killer_account_id)
        )
    ).all()

    kills = (
        await session.execute(
            select(
                KillEvent.victim_account_id.label("acct"),
                func.count().label("n"),
                func.max(Match.played_at).label("last"),
            )
            .join(Match, Match.match_id == KillEvent.match_id)
            .where(
                KillEvent.killer_account_id == account_id,
                KillEvent.victim_is_bot.is_(False),
                KillEvent.is_suicide.is_(False),
                career_filter(),
            )
            .group_by(KillEvent.victim_account_id)
        )
    ).all()

    tally: dict[str, dict[str, object]] = {}
    for acct, n, last in deaths:
        tally.setdefault(acct, {"killed_by": 0, "killed": 0, "last": None})
        tally[acct]["killed_by"] = int(n)
        tally[acct]["last"] = last
    for acct, n, last in kills:
        entry = tally.setdefault(acct, {"killed_by": 0, "killed": 0, "last": None})
        entry["killed"] = int(n)
        prior = entry["last"]
        if prior is None or (last is not None and last > prior):  # type: ignore[operator]
            entry["last"] = last

    tally.pop(account_id, None)
    if not tally:
        return []

    names = await _latest_names(session, list(tally))
    ranked = sorted(
        tally.items(),
        key=lambda kv: (-int(kv[1]["killed_by"]), -int(kv[1]["killed"])),  # type: ignore[call-overload]
    )[:limit]

    return [
        Nemesis(
            account_id=acct,
            name=names.get(acct, acct),
            killed_by=int(v["killed_by"]),  # type: ignore[arg-type]
            killed=int(v["killed"]),  # type: ignore[arg-type]
            last_seen=v["last"],  # type: ignore[arg-type]
        )
        for acct, v in ranked
    ]


async def _latest_names(
    session: AsyncSession, account_ids: list[str]
) -> dict[str, str]:
    """Most recent in-match name for each account.

    Names are read from `participants` because opponents may have no `players`
    row, and PUBG lets people rename — the newest observation is the one worth
    showing.
    """
    if not account_ids:
        return {}
    rows = (
        await session.execute(
            select(Participant.account_id, Participant.name)
            .join(Match, Match.match_id == Participant.match_id)
            .where(Participant.account_id.in_(account_ids))
            .distinct(Participant.account_id)
            .order_by(Participant.account_id, Match.played_at.desc())
        )
    ).all()
    return {acct: name for acct, name in rows}


@router.get("/{account_id}/timeseries", response_model=list[TimeseriesPoint])
async def player_timeseries(
    session: SessionDep,
    account_id: str,
    metric: Annotated[
        str, Query(pattern="^(kills|damage|winPlace|survival|kd|accuracy)$")
    ] = "kills",
    include_bots: Annotated[bool, Query(alias="includeBots")] = False,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
) -> list[TimeseriesPoint]:
    """Daily aggregate of one metric over career matches.

    `kd` and `accuracy` are ratios of sums, not averages of per-match ratios:
    a day with one 0-kill match and one 6-kill match has a K/D of 3, and
    averaging the per-match values would agree here but not once matches
    carry different weights.
    """
    where = [
        Participant.account_id == account_id,
        career_filter(),
        Match.played_at >= dt.datetime.now(dt.UTC) - dt.timedelta(days=days),
    ]
    if game_mode:
        where.append(Match.game_mode == game_mode)

    day = func.date_trunc("day", Match.played_at)
    kills = kills_column(include_bots)

    if metric == "kd":
        value = cast(func.sum(kills), Float) / func.nullif(func.count(), 0)
    elif metric == "accuracy":
        value = cast(func.coalesce(func.sum(Participant.shots_hit), 0), Float) / func.nullif(
            func.coalesce(func.sum(Participant.shots_fired), 0), 0
        )
    elif metric == "winPlace":
        # A mean rank is meaningful; a sum of ranks is not.
        value = func.avg(cast(Participant.win_place, Float))
    elif metric == "damage":
        value = func.sum(Participant.damage_dealt)
    elif metric == "survival":
        value = func.sum(Participant.time_survived)
    else:
        value = func.sum(kills)

    rows = (
        await session.execute(
            select(day.label("day"), func.count().label("n"), value.label("value"))
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(and_(*where))
            .group_by(day)
            .order_by(day)
        )
    ).all()

    return [
        TimeseriesPoint(day=d.date(), matches=n, value=float(v or 0.0)) for d, n, v in rows
    ]


@router.get("/{account_id}/sessions", response_model=list[dict])
async def player_sessions(
    session: SessionDep,
    account_id: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict]:
    """Recent play sessions — runs of matches with less than a 3 h gap.

    A calendar day is the wrong unit: a session that starts at 22:00 and runs
    to 01:30 is one evening, and grouping by date splits it in two.
    """
    rows = (
        await session.execute(
            select(Match.match_id, Match.played_at, Match.duration_s, Participant.win_place,
                   func.coalesce(Participant.kills_human, Participant.kills))
            .join(Match, Match.match_id == Participant.match_id)
            .where(Participant.account_id == account_id, career_filter())
            .order_by(Match.played_at.desc())
            .limit(200)
        )
    ).all()

    out: list[dict] = []
    current: list[tuple] = []
    for row in rows:
        if current and (current[-1][1] - row[1]).total_seconds() > SESSION_GAP_S:
            out.append(_session_row(current))
            current = []
            if len(out) >= limit:
                return out
        current.append(row)
    if current:
        out.append(_session_row(current))
    return out[:limit]


#: Matches further apart than this start a new session. Three hours is longer
#: than any single match plus a break, and shorter than a night's sleep.
SESSION_GAP_S = 3 * 3600


def _session_row(rows: list[tuple]) -> dict:
    """Rows are newest-first within a session."""
    return {
        "startedAt": rows[-1][1],
        "endedAt": rows[0][1],
        "matches": len(rows),
        "bestPlace": min(r[3] for r in rows),
        "wins": sum(1 for r in rows if r[3] == 1),
        "kills": sum(int(r[4] or 0) for r in rows),
    }


__all__ = ["SESSION_GAP_S", "career_stats", "router"]
