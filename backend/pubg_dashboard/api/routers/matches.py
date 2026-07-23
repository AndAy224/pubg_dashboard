"""Match feed, scoreboard, kill feed, and the replay bundle."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from pubg_dashboard.api.schemas import (
    KillRow,
    MatchDetail,
    MatchFeedRow,
    ParticipantRow,
    RosterRow,
    TrackedResult,
)
from pubg_dashboard.db.models import KillEvent, Match, Participant, Player, Roster
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.maps import display_name, world_size

router = APIRouter(prefix="/matches", tags=["matches"])


# ---------------------------------------------------------------------------
# The enriched feed
# ---------------------------------------------------------------------------
async def match_feed(
    session: AsyncSession,
    *,
    limit: int = 20,
    tracked_only: bool = True,
    account_id: str | None = None,
    before: dt.datetime | None = None,
    map_name: str | None = None,
    game_mode: str | None = None,
    match_type: str | None = None,
    has_replay: bool | None = None,
) -> list[MatchFeedRow]:
    """Recent matches **with the tracked players' results attached**.

    Two statements rather than one join: the first picks the page of matches,
    the second fetches every tracked participant in them. Joining in one
    statement would multiply each match by its number of tracked participants
    *before* LIMIT applied, so a page of 20 would silently return 8 matches on
    a night the three of them squadded.

    The killer's name is resolved by a self-join on `participants`, never on
    `players`: bot ids are match-scoped and bots have no player row at all, so
    a `players` join would blank the ~19% of deaths caused by one.
    """
    where = []
    if before:
        where.append(Match.played_at < before)
    if map_name:
        where.append(Match.map_name == map_name)
    if game_mode:
        where.append(Match.game_mode == game_mode)
    if match_type:
        where.append(Match.match_type == match_type)
    if has_replay is not None:
        where.append(
            Match.replay_key.is_not(None) if has_replay else Match.replay_key.is_(None)
        )

    if account_id:
        where.append(
            exists(
                select(1)
                .select_from(Participant)
                .where(
                    Participant.match_id == Match.match_id,
                    Participant.account_id == account_id,
                )
            )
        )
    elif tracked_only:
        # EXISTS, not COUNT(*) > 0: it stops at the first hit instead of
        # counting every tracked participant in the match.
        where.append(
            exists(
                select(1)
                .select_from(Participant)
                .join(Player, Player.account_id == Participant.account_id)
                .where(Participant.match_id == Match.match_id, Player.tracked)
            )
        )

    matches = (
        (
            await session.execute(
                select(Match)
                .where(and_(*where) if where else True)
                .order_by(Match.played_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not matches:
        return []

    ids = [m.match_id for m in matches]
    killer = aliased(Participant, name="killer")
    rows = (
        await session.execute(
            select(
                Participant,
                Player.name,
                Roster.won,
                Roster.rank,
                killer.name,
                killer.is_bot,
            )
            .select_from(Participant)
            .join(
                Player,
                and_(Player.account_id == Participant.account_id, Player.tracked),
            )
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
            .where(Participant.match_id.in_(ids))
            .order_by(Participant.match_id, Player.name)
        )
    ).all()

    results: dict[str, list[TrackedResult]] = {}
    placement: dict[str, tuple[int, bool]] = {}
    for p, player_name, won, _rank, killer_name, killer_is_bot in rows:
        results.setdefault(p.match_id, []).append(
            TrackedResult(
                account_id=p.account_id,
                name=player_name or p.name,
                team_id=p.team_id,
                win_place=p.win_place,
                kills=p.kills,
                kills_human=p.kills_human,
                knocks=p.dbnos,
                assists=p.assists,
                damage_dealt=p.damage_dealt,
                time_survived=p.time_survived,
                death_type=p.death_type,
                headshot_kills=p.headshot_kills,
                shots_fired=p.shots_fired,
                shots_hit=p.shots_hit,
                killed_by=killer_name,
                killed_by_is_bot=killer_is_bot,
                death_weapon=p.death_weapon,
            )
        )
        # Same roster every time they play together (verified across the
        # archive), so the last writer wins harmlessly.
        placement[p.match_id] = (p.win_place, bool(won))

    return [
        MatchFeedRow(
            match_id=m.match_id,
            played_at=m.played_at,
            telemetry_t0=m.telemetry_t0,
            map_name=m.map_name,
            map_display=display_name(m.map_name),
            game_mode=m.game_mode,
            match_type=m.match_type,
            duration_s=m.duration_s,
            has_replay=m.replay_key is not None,
            parsed=m.telemetry_parsed_at is not None,
            weather_id=m.weather_id,
            bot_count=m.bot_count,
            num_start_players=m.num_start_players,
            num_start_teams=m.num_start_teams,
            team_size=m.team_size,
            win_place=placement.get(m.match_id, (None, False))[0],
            won=placement.get(m.match_id, (None, False))[1],
            results=results.get(m.match_id, []),
        )
        for m in matches
    ]


@router.get("", response_model=list[MatchFeedRow])
async def recent_matches(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    tracked_only: Annotated[bool, Query(alias="trackedOnly")] = True,
    account_id: Annotated[
        str | None, Query(alias="accountId", description="Only matches this player was in.")
    ] = None,
    before: Annotated[
        dt.datetime | None, Query(description="Keyset cursor on playedAt.")
    ] = None,
    map_name: Annotated[str | None, Query(alias="map")] = None,
    game_mode: Annotated[str | None, Query(alias="gameMode")] = None,
    match_type: Annotated[str | None, Query(alias="matchType")] = None,
    has_replay: Annotated[bool | None, Query(alias="hasReplay")] = None,
) -> list[MatchFeedRow]:
    """The match archive, newest first, with tracked-player results attached.

    Paginated by keyset on `played_at` rather than OFFSET: matches arrive at
    the head continuously, and an offset page would repeat or skip rows as
    they do.
    """
    return await match_feed(
        session,
        limit=limit,
        tracked_only=tracked_only,
        account_id=account_id,
        before=before,
        map_name=map_name,
        game_mode=game_mode,
        match_type=match_type,
        has_replay=has_replay,
    )


# ---------------------------------------------------------------------------
# One match
# ---------------------------------------------------------------------------
@router.get("/{match_id}", response_model=MatchDetail)
async def match_detail(session: SessionDep, match_id: str) -> MatchDetail:
    """Full scoreboard, grouped by roster.

    Participants carry no team id of their own — the only link is through the
    roster — so the grouping is the data model, not a presentation choice.
    """
    match = await session.get(Match, match_id)
    if match is None:
        raise HTTPException(404, f"unknown match {match_id}")

    rosters = (
        (
            await session.execute(
                select(Roster).where(Roster.match_id == match_id).order_by(Roster.rank)
            )
        )
        .scalars()
        .all()
    )

    rows = (
        await session.execute(
            select(Participant, Player.tracked)
            .outerjoin(Player, Player.account_id == Participant.account_id)
            .where(Participant.match_id == match_id)
            .order_by(Participant.team_id, Participant.kills.desc())
        )
    ).all()

    by_team: dict[int, list[ParticipantRow]] = {}
    for p, tracked in rows:
        by_team.setdefault(p.team_id, []).append(
            ParticipantRow(
                account_id=p.account_id,
                name=p.name,
                team_id=p.team_id,
                is_bot=p.is_bot,
                kills=p.kills,
                kills_human=p.kills_human,
                assists=p.assists,
                dbnos=p.dbnos,
                damage_dealt=p.damage_dealt,
                headshot_kills=p.headshot_kills,
                heals=p.heals,
                boosts=p.boosts,
                revives=p.revives,
                longest_kill=p.longest_kill,
                time_survived=p.time_survived,
                walk_distance=p.walk_distance,
                ride_distance=p.ride_distance,
                win_place=p.win_place,
                death_type=p.death_type,
                tracked=bool(tracked),
                shots_fired=p.shots_fired,
                shots_hit=p.shots_hit,
                knocks_human=p.knocks_human,
                landing_x=p.landing_x,
                landing_y=p.landing_y,
                death_x=p.death_x,
                death_y=p.death_y,
                died_at_s=p.died_at_s,
                killer_account_id=p.killer_account_id,
                death_weapon=p.death_weapon,
                weapons_acquired=p.weapons_acquired,
                kill_streaks=p.kill_streaks,
                road_kills=p.road_kills,
                vehicle_destroys=p.vehicle_destroys,
                team_kills=p.team_kills,
                swim_distance=p.swim_distance,
            )
        )

    return MatchDetail(
        match_id=match.match_id,
        shard=match.shard,
        played_at=match.played_at,
        telemetry_t0=match.telemetry_t0,
        map_name=match.map_name,
        map_display=display_name(match.map_name),
        world_size=world_size(match.map_name),
        game_mode=match.game_mode,
        match_type=match.match_type,
        duration_s=match.duration_s,
        team_size=match.team_size,
        weather_id=match.weather_id,
        is_custom_match=match.is_custom_match,
        parsed=match.telemetry_parsed_at is not None,
        has_replay=match.replay_key is not None,
        bot_count=match.bot_count,
        num_start_players=match.num_start_players,
        num_start_teams=match.num_start_teams,
        camera_view=match.camera_view,
        rosters=[
            RosterRow(
                team_id=r.team_id,
                rank=r.rank,
                won=r.won,
                participants=by_team.get(r.team_id, []),
            )
            for r in rosters
        ],
    )


@router.get("/{match_id}/kills", response_model=list[KillRow])
async def match_kills(
    session: SessionDep,
    match_id: str,
    include_bots: Annotated[bool, Query(alias="includeBots")] = True,
) -> list[KillRow]:
    """Kill feed in match order, with positions for the kill map.

    Names are resolved from a single `participants` fetch for the match, not
    from `players`: bots have no player row at all (their `ai.<n>` ids are
    match-scoped and recycled), so a join to `players` would silently blank
    every bot in the feed. One dict lookup also resolves the assist arrays,
    which no join can do without fanning out the result set.
    """
    where = [KillEvent.match_id == match_id]
    if not include_bots:
        where.append(KillEvent.victim_is_bot.is_(False))

    names = dict(
        (
            await session.execute(
                select(Participant.account_id, Participant.name).where(
                    Participant.match_id == match_id
                )
            )
        ).all()
    )
    bots = set(
        (
            await session.execute(
                select(Participant.account_id).where(
                    Participant.match_id == match_id, Participant.is_bot
                )
            )
        )
        .scalars()
        .all()
    )

    kills = (
        (
            await session.execute(
                select(KillEvent).where(and_(*where)).order_by(KillEvent.seq)
            )
        )
        .scalars()
        .all()
    )

    return [
        KillRow(
            seq=k.seq,
            t_s=k.t_s,
            victim_account_id=k.victim_account_id,
            victim_name=names.get(k.victim_account_id),
            victim_is_bot=k.victim_is_bot,
            victim_team_id=k.victim_team_id,
            killer_account_id=k.killer_account_id,
            killer_name=names.get(k.killer_account_id) if k.killer_account_id else None,
            killer_is_bot=(
                k.killer_account_id in bots if k.killer_account_id else None
            ),
            killer_team_id=k.killer_team_id,
            weapon=k.weapon,
            damage_reason=k.damage_reason,
            # -1 is the "not applicable" sentinel, not a distance.
            distance_m=(
                k.distance_cm / 100.0
                if k.distance_cm is not None and k.distance_cm > 0
                else None
            ),
            is_suicide=k.is_suicide,
            is_team_kill=k.is_team_kill,
            victim_x=k.victim_x,
            victim_y=k.victim_y,
            killer_x=k.killer_x,
            killer_y=k.killer_y,
            assists=[names.get(a, a) for a in (k.assists or [])],
        )
        for k in kills
    ]


@router.get(
    "/{match_id}/replay",
    responses={200: {"content": {"application/vnd.msgpack": {}}}},
    response_class=Response,
)
async def match_replay(session: SessionDep, match_id: str) -> Response:
    """The processed replay bundle: gzipped MessagePack.

    Streamed straight from object storage with a one-year immutable cache: a
    bundle for a given `parser_version` never changes, and the version is part
    of the object key, so bumping the parser invalidates cleanly rather than
    needing a purge.

    The body is served **still gzipped**, with `Content-Encoding: gzip`, so it
    is never decompressed and recompressed on the way through.
    """
    from pubg_dashboard.storage.factory import get_storage

    row = (
        await session.execute(
            select(Match.replay_key, Match.parser_version).where(Match.match_id == match_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, f"unknown match {match_id}")
    key, version = row
    if not key:
        raise HTTPException(
            409, f"{match_id} has no replay bundle yet; it has not been parsed"
        )

    try:
        blob = await get_storage().get(key)
    except Exception as exc:
        raise HTTPException(404, f"replay bundle missing from storage: {key}") from exc

    return Response(
        content=blob,
        media_type="application/vnd.msgpack",
        headers={
            "Content-Encoding": "gzip",
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Parser-Version": str(version or 0),
        },
    )
