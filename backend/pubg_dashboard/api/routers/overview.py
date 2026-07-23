"""The home page in one request.

The overview used to cost five: a player list, one career-stats call per
tracked player, a match feed, and health. They all hit the same small set of
tables, so composing them server-side removes four round trips and, more
usefully, removes the four separate loading states that made the page flicker
into existence a card at a time.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.api.deps import career_filter
from pubg_dashboard.api.routers.health import health as health_endpoint
from pubg_dashboard.api.routers.matches import match_feed
from pubg_dashboard.api.routers.players import SESSION_GAP_S, career_stats
from pubg_dashboard.api.schemas import (
    FormEntry,
    MatchFeedRow,
    Overview,
    PlayerCard,
    PlayerSummary,
    SessionSummary,
)
from pubg_dashboard.db.models import Match, Participant, Player
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.maps import display_name

router = APIRouter(tags=["overview"])

#: How many recent results the form strip shows.
FORM_LENGTH = 10


@router.get("/overview", response_model=Overview)
async def overview(
    session: SessionDep,
    matches: Annotated[int, Query(ge=1, le=50)] = 12,
    delta_days: Annotated[
        int,
        Query(
            alias="deltaDays",
            ge=1,
            le=90,
            description="Length of each trend-comparison window, in days.",
        ),
    ] = 7,
) -> Overview:
    now = dt.datetime.now(dt.UTC)
    window = dt.timedelta(days=delta_days)

    players = (
        (
            await session.execute(
                select(Player).where(Player.tracked).order_by(Player.name)
            )
        )
        .scalars()
        .all()
    )

    played = dict(
        (
            await session.execute(
                select(
                    Participant.account_id,
                    func.count(),
                )
                .where(Participant.account_id.in_([p.account_id for p in players]))
                .group_by(Participant.account_id)
            )
        ).all()
    ) if players else {}

    last_seen = dict(
        (
            await session.execute(
                select(Participant.account_id, func.max(Match.played_at))
                .join(Match, Match.match_id == Participant.match_id)
                .where(Participant.account_id.in_([p.account_id for p in players]))
                .group_by(Participant.account_id)
            )
        ).all()
    ) if players else {}

    summaries = []
    for p in players:
        summaries.append(
            PlayerSummary(
                card=PlayerCard(
                    account_id=p.account_id,
                    name=p.name,
                    shard=p.shard,
                    tracked=p.tracked,
                    matches=played.get(p.account_id, 0),
                    last_seen=last_seen.get(p.account_id),
                    last_polled_at=p.last_polled_at,
                    consecutive_poll_failures=p.consecutive_poll_failures,
                ),
                stats=await career_stats(session, p.account_id, name=p.name),
                form=await _form(session, p.account_id),
                recent=await career_stats(
                    session, p.account_id, name=p.name, since=now - window
                ),
                previous=await career_stats(
                    session,
                    p.account_id,
                    name=p.name,
                    since=now - 2 * window,
                    until=now - window,
                ),
            )
        )

    feed = await match_feed(session, limit=matches, tracked_only=True)
    return Overview(
        players=summaries,
        matches=feed,
        health=await health_endpoint(session),
        session=_session_summary(feed),
    )


async def _form(session: AsyncSession, account_id: str) -> list[FormEntry]:
    """The last N career results, **oldest first** so the strip reads left to
    right like a calendar."""
    rows = (
        await session.execute(
            select(
                Match.match_id,
                Match.played_at,
                Match.map_name,
                Match.game_mode,
                Match.num_start_teams,
                Participant.win_place,
                func.coalesce(Participant.kills_human, Participant.kills),
            )
            .select_from(Participant)
            .join(Match, Match.match_id == Participant.match_id)
            .where(and_(Participant.account_id == account_id, career_filter()))
            .order_by(Match.played_at.desc())
            .limit(FORM_LENGTH)
        )
    ).all()

    return [
        FormEntry(
            match_id=mid,
            played_at=at,
            win_place=place,
            num_start_teams=teams,
            kills=int(kills or 0),
            map_display=display_name(map_name),
            game_mode=mode,
        )
        for mid, at, map_name, mode, teams, place, kills in reversed(rows)
    ]


def _session_summary(feed: list[MatchFeedRow]) -> SessionSummary | None:
    """The most recent play session, read straight off the feed.

    A session is a run of matches less than `SESSION_GAP_S` apart — the unit
    people actually remember ("how did we do tonight"). A calendar day would
    split an evening that runs past midnight, which is exactly when these
    three play.

    Kills are summed across tracked players because the session is the group's,
    not one player's; placement is the best (numerically lowest) of the run.
    """
    if not feed:
        return None

    run = [feed[0]]
    for row in feed[1:]:
        if (run[-1].played_at - row.played_at).total_seconds() > SESSION_GAP_S:
            break
        run.append(row)

    places = [r.win_place for r in run if r.win_place is not None]
    return SessionSummary(
        matches=len(run),
        started_at=run[-1].played_at,
        ended_at=run[0].played_at,
        best_place=min(places) if places else 0,
        wins=sum(1 for p in places if p == 1),
        kills_human=sum(
            (t.kills_human if t.kills_human is not None else t.kills)
            for r in run
            for t in r.results
        ),
        damage=sum(t.damage_dealt for r in run for t in r.results),
        span_s=(run[0].played_at - run[-1].played_at).total_seconds()
        + run[0].duration_s,
    )
