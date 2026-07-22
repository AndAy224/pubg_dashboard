"""Heatmap reads.

Bins are precomputed by the parser across the cross product of
{this player, all players} x {this mode, all modes}, so every filter
combination is an indexed lookup rather than a scan. The `''` sentinels are
the "all" rows — they are real values in the primary key, not NULLs.
"""

from __future__ import annotations

import base64
import datetime as dt
from array import array
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from pubg_dashboard.api.schemas import Heatmap
from pubg_dashboard.db.models import HeatmapBin
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.telemetry.heatmap import GRID, KINDS
from pubg_dashboard.telemetry.maps import world_size

router = APIRouter(tags=["heatmap"])


@router.get("/heatmap", response_model=Heatmap)
async def heatmap(
    session: SessionDep,
    map_name: Annotated[str, Query(alias="map")] = "Baltic_Main",
    kind: Annotated[str, Query()] = "movement",
    account_id: Annotated[
        str | None, Query(alias="accountId", description="Omit for all players.")
    ] = None,
    game_mode: Annotated[
        str | None, Query(alias="gameMode", description="Omit for all modes.")
    ] = None,
    since: Annotated[dt.date | None, Query()] = None,
    until: Annotated[dt.date | None, Query()] = None,
) -> Heatmap:
    """A dense `grid x grid` Uint32 array, base64 encoded.

    Dense rather than sparse: 256x256x4 B is 256 KB, roughly 10 KB after
    gzip, and the client wants to upload it as a texture. A sparse list would
    be larger for a busy map and would still need expanding on the main thread.

    Row-major (`y * grid + x`), and **y is not flipped** — telemetry's origin
    is top-left with y growing downward, exactly like canvas.

    **Known inconsistency with career stats.** `heatmap_bins` has no
    `match_type` dimension, so these counts include `airoyale` and
    `tutorialatoz` while `/players/{id}/stats` counts `official` only. One
    tracked player shows 28 career kills against 48 binned. Neither number is
    wrong, but they answer different questions and a UI that puts them side by
    side should say so. Fixing it properly means adding `match_type` to the
    bin key and reparsing — cheap in wall-clock (the raw telemetry is all
    stored) but it is a schema change, so it is deliberately not done here.
    """
    where = [
        HeatmapBin.map_name == map_name,
        HeatmapBin.kind == kind,
        # '' is the aggregate row, and it is a real value rather than a NULL
        # precisely so this comparison works.
        HeatmapBin.account_id == (account_id or ""),
        HeatmapBin.game_mode == (game_mode or ""),
    ]
    if since:
        where.append(HeatmapBin.day >= since)
    if until:
        where.append(HeatmapBin.day <= until)

    rows = (
        await session.execute(
            select(
                HeatmapBin.grid_x,
                HeatmapBin.grid_y,
                func.sum(HeatmapBin.count).label("n"),
            )
            .where(and_(*where))
            .group_by(HeatmapBin.grid_x, HeatmapBin.grid_y)
        )
    ).all()

    cells = array("I", bytes(GRID * GRID * 4))
    peak = 0
    total = 0
    for gx, gy, n in rows:
        value = int(n or 0)
        if value <= 0:
            continue
        cells[gy * GRID + gx] = value
        total += value
        peak = max(peak, value)

    return Heatmap(
        map_name=map_name,
        kind=kind,
        grid=GRID,
        world_size=world_size(map_name),
        max=peak,
        total=total,
        cells=base64.b64encode(_le(cells)).decode("ascii"),
    )


@router.get("/heatmap/kinds", response_model=list[str])
async def heatmap_kinds() -> list[str]:
    return list(KINDS)


def _le(arr: array) -> bytes:
    """Little-endian bytes regardless of host order — the client assumes LE."""
    import sys

    if sys.byteorder != "little":
        arr = array(arr.typecode, arr)
        arr.byteswap()
    return arr.tobytes()
