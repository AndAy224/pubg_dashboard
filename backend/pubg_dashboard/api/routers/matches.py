"""Match scoreboard, kill feed, and the replay bundle."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import and_, func, select

from pubg_dashboard.api.schemas import (
    KillRow,
    MatchDetail,
    ParticipantRow,
    RosterRow,
)
from pubg_dashboard.db.models import KillEvent, Match, Participant, Player, Roster
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.maps import display_name, world_size

router = APIRouter(prefix="/matches", tags=["matches"])


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
        await session.execute(
            select(Roster).where(Roster.match_id == match_id).order_by(Roster.rank)
        )
    ).scalars().all()

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
    """Kill feed in match order.

    Names are joined from `participants`, not `players`: bots have no player
    row at all (their `ai.<n>` ids are match-scoped and recycled), so a join to
    `players` would silently blank every bot in the feed.
    """
    where = [KillEvent.match_id == match_id]
    if not include_bots:
        where.append(KillEvent.victim_is_bot.is_(False))

    victim = Participant.__table__.alias("victim")
    killer = Participant.__table__.alias("killer")
    rows = (
        await session.execute(
            select(KillEvent, victim.c.name, killer.c.name)
            .outerjoin(
                victim,
                and_(
                    victim.c.match_id == KillEvent.match_id,
                    victim.c.account_id == KillEvent.victim_account_id,
                ),
            )
            .outerjoin(
                killer,
                and_(
                    killer.c.match_id == KillEvent.match_id,
                    killer.c.account_id == KillEvent.killer_account_id,
                ),
            )
            .where(and_(*where))
            .order_by(KillEvent.seq)
        )
    ).all()

    return [
        KillRow(
            seq=k.seq,
            t_s=k.t_s,
            victim_account_id=k.victim_account_id,
            victim_name=vname,
            victim_is_bot=k.victim_is_bot,
            killer_account_id=k.killer_account_id,
            killer_name=kname,
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
        )
        for k, vname, kname in rows
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


@router.get("", response_model=list[dict])
async def recent_matches(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    tracked_only: Annotated[bool, Query(alias="trackedOnly")] = True,
) -> list[dict]:
    """Recent-match feed for the home page."""
    stmt = select(Match).order_by(Match.played_at.desc()).limit(limit)
    if tracked_only:
        stmt = stmt.where(
            select(func.count())
            .select_from(Participant)
            .join(Player, Player.account_id == Participant.account_id)
            .where(Participant.match_id == Match.match_id, Player.tracked)
            .scalar_subquery()
            > 0
        )
    return [
        {
            "matchId": m.match_id,
            "playedAt": m.played_at,
            "mapName": m.map_name,
            "mapDisplay": display_name(m.map_name),
            "gameMode": m.game_mode,
            "matchType": m.match_type,
            "durationS": m.duration_s,
            "hasReplay": m.replay_key is not None,
        }
        for m in (await session.execute(stmt)).scalars().all()
    ]
