"""Where the squad lands, joined to how the match went.

The heatmaps have always shown *where* landings happen. They have never shown
whether landing there worked. Every input for that has been in Postgres since
parser v7 — `participants.landing_x/y`, `landed_at_s`, and the placement and
survival on the same row — so this router needs no reparse and no migration.

**Rows, not clusters.** Clustering and labelling happen in
`frontend/src/lib/drops.ts`, where they are pure functions with hermetic tests.
The server's job is the join, exactly as `strategy.py` does it.

The one thing this router *does* decide is the grain: a row is one **(match,
team)** pair, not one participant. That is not a detail. The three tracked
players are always on the same roster when they play together, so keying on
participants would count a single squad landing up to three times — turning a
cluster with 19 real drops into a confident-looking 48.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, func, select

from pubg_dashboard.api.deps import MatchScopeDep, career_filter
from pubg_dashboard.api.schemas import DropRow, Gazetteer, PlaceCell
from pubg_dashboard.db.models import Match, Participant, Player, StrategyMetric
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.gazetteer import available_maps, load_gazetteer

router = APIRouter(tags=["drops"])


@router.get("/strategy/drops", response_model=list[DropRow])
async def squad_drops(
    session: SessionDep,
    scope: MatchScopeDep,
) -> list[DropRow]:
    """One row per squad landing, newest first.

    Career matches only, and only matches a tracked player landed in —
    `landing_x` is NULL for anyone who never opened a parachute (disconnects,
    and the handful of matches parsed before v7 wrote the column).

    A player who redeploys by flare gun lands twice; `landed_at_s` is the
    **first** landing, which is what `FrameIndex.landing` records and what "the
    drop" means.
    """
    stmt = (
        select(
            Match.match_id,
            Match.played_at,
            Match.map_name,
            Match.game_mode,
            Participant.team_id,
            func.avg(Participant.landing_x),
            func.avg(Participant.landing_y),
            func.min(Participant.landed_at_s),
            func.min(Participant.win_place),
            func.sum(func.coalesce(Participant.kills_human, Participant.kills)),
            func.max(Participant.time_survived),
            func.max(StrategyMetric.hot_drop_n),
            func.avg(StrategyMetric.first_weapon_s),
            func.array_agg(Participant.name),
            func.array_agg(Participant.landing_x),
            func.array_agg(Participant.landing_y),
        )
        .select_from(Participant)
        .join(Match, Match.match_id == Participant.match_id)
        .join(Player, Player.account_id == Participant.account_id)
        # Outer, not inner: a match parsed before v7 has no strategy row, and
        # dropping it would silently shrink the sample rather than show the
        # landing with a missing contested count.
        .outerjoin(
            StrategyMetric,
            (StrategyMetric.match_id == Participant.match_id)
            & (StrategyMetric.account_id == Participant.account_id),
        )
        .where(Player.tracked, career_filter(), Participant.landing_x.is_not(None))
        .group_by(
            Match.match_id, Match.played_at, Match.map_name, Match.game_mode, Participant.team_id
        )
        .order_by(desc(Match.played_at))
    )
    # The same `?map=`/`?gameMode=` every other aggregate takes. This endpoint
    # shipped them first and defined the aliases; `MatchScope` adopted them so
    # one URL filters the whole Strategy page rather than just this panel.
    stmt = stmt.where(*scope.predicates())

    out: list[DropRow] = []
    for row in (await session.execute(stmt)).all():
        (
            match_id,
            played_at,
            map_name_,
            game_mode_,
            team_id,
            cx,
            cy,
            landed_at,
            win_place,
            kills,
            survived,
            contested,
            first_weapon,
            names,
            xs,
            ys,
        ) = row
        out.append(
            DropRow(
                match_id=match_id,
                played_at=played_at,
                map_name=map_name_,
                game_mode=game_mode_,
                team_id=int(team_id),
                x=float(cx),
                y=float(cy),
                spread_cm=_spread(float(cx), float(cy), xs, ys),
                landed_at_s=None if landed_at is None else float(landed_at),
                win_place=int(win_place or 0),
                kills=int(kills or 0),
                time_survived=float(survived or 0.0),
                contested=None if contested is None else int(contested),
                first_weapon_s=None if first_weapon is None else float(first_weapon),
                names=[n for n in names if n],
            )
        )
    return out


def _spread(cx: float, cy: float, xs: list[float | None], ys: list[float | None]) -> float:
    """Furthest landing from the team centroid, centimetres.

    Reported so a squad that split the drop is visible as such. Averaging two
    players who landed a kilometre apart puts the marker in a field neither of
    them saw, and nothing else on the row would say so.
    """
    worst = 0.0
    for x, y in zip(xs, ys, strict=False):
        if x is None or y is None:
            continue
        worst = max(worst, math.dist((cx, cy), (float(x), float(y))))
    return worst


@router.get("/maps/{map_name}/places", response_model=Gazetteer)
async def map_places(map_name: str) -> Gazetteer:
    """PUBG's own place names for a map, as grid cells.

    404 when no gazetteer has been built, and the message **names the actual
    cause** rather than saying "not found": the map is almost certainly fine,
    it just has no telemetry in `data/` yet, and the fix is one script.
    """
    gaz = load_gazetteer(map_name)
    if gaz is None:
        built = ", ".join(available_maps()) or "none"
        raise HTTPException(
            status_code=404,
            detail=(
                f"no place-name gazetteer built for {map_name!r} — it needs raw "
                f"telemetry under data/ and a run of scripts/build_gazetteer.py. "
                f"Built so far: {built}."
            ),
        )
    return Gazetteer(
        map_name=gaz.map_name,
        grid=gaz.grid,
        world_size=gaz.world_size,
        cells=[
            PlaceCell(gx=gx, gy=gy, name=gaz.names[idx], support=support)
            for (gx, gy), (idx, support) in sorted(gaz.cells.items())
        ],
        matches=int(gaz.built_from.get("matches", 0)),
        samples=int(gaz.built_from.get("samples", 0)),
        modal_purity=float(gaz.built_from.get("modalPurity", 0.0)),
    )


__all__ = ["router"]
