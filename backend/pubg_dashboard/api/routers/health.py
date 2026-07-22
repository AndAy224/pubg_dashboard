"""Health and map metadata."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from pubg_dashboard.api.schemas import Health, MapInfo
from pubg_dashboard.db.models import Job, Match, Player
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.bundle import PARSER_VERSION
from pubg_dashboard.telemetry.maps import (
    MAP_WORLD_SIZE,
    asset_base,
    display_name,
    image_scale,
)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health)
async def health(session: SessionDep) -> Health:
    """Liveness plus the numbers an operator actually checks.

    `poller_lag_s` is the important one: PUBG discards match history after ~14
    days, so a lag that climbs is the early warning that matches are being lost
    permanently. Everything else here recovers on its own.
    """
    matches = await session.scalar(select(func.count()).select_from(Match)) or 0
    parsed = (
        await session.scalar(
            select(func.count())
            .select_from(Match)
            .where(Match.telemetry_parsed_at.is_not(None))
        )
        or 0
    )
    pending = (
        await session.scalar(
            select(func.count()).select_from(Job).where(Job.state.in_(("pending", "running")))
        )
        or 0
    )
    failed = (
        await session.scalar(
            select(func.count()).select_from(Job).where(Job.state == "failed")
        )
        or 0
    )
    # Stalest tracked player. NULL last_polled_at (never polled) reads as
    # "infinitely stale", so it is reported as None rather than 0 — a
    # never-polled player is a different problem from a lagging one.
    lag = await session.scalar(
        select(func.min(func.extract("epoch", func.now() - Player.last_polled_at))).where(
            Player.tracked, Player.last_polled_at.is_not(None)
        )
    )

    storage_ok = True
    try:
        from pubg_dashboard.storage.factory import get_storage

        await get_storage().exists("health-probe-does-not-exist")
    except Exception:
        storage_ok = False

    return Health(
        db=True,
        storage=storage_ok,
        matches=matches,
        parsed=parsed,
        queue_pending=pending,
        queue_failed=failed,
        poller_lag_s=float(lag) if lag is not None else None,
        parser_version=PARSER_VERSION,
    )


@router.get("/maps", response_model=list[MapInfo])
async def maps() -> list[MapInfo]:
    """Every known map, with the geometry the client needs to place a dot.

    `imageScale` is the 8160/8192 correction, which applies **only** to the
    816000-cm maps. Skip it there and every point drifts ~0.4% — 32 m at the
    edge of Erangel, enough to put a kill in the sea.
    """
    return [
        MapInfo(
            map_name=name,
            display=display_name(name),
            world_size=size,
            asset_base=asset_base(name),
            image_scale=image_scale(name),
        )
        for name, size in sorted(MAP_WORLD_SIZE.items())
    ]


@router.get("/maps/played", response_model=list[MapInfo])
async def maps_played(session: SessionDep) -> list[MapInfo]:
    """Only the maps actually present in the archive.

    The map-picker should not offer Karakin when nobody has played it.
    """
    rows = (await session.execute(select(Match.map_name).distinct().order_by(Match.map_name))).all()
    return [
        MapInfo(
            map_name=name,
            display=display_name(name),
            world_size=MAP_WORLD_SIZE.get(name, 816_000),
            asset_base=asset_base(name),
            image_scale=image_scale(name),
        )
        for (name,) in rows
    ]
