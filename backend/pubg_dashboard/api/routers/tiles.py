"""Map tile pyramid, produced by `scripts/fetch_map_assets.py`.

Served from the API rather than a separate web server because this is a LAN
dashboard for three people. In front of a real deployment, hand `/api/tiles`
to the reverse proxy instead — a static file server will always beat uvicorn at
this, and the tiles are immutable so it is pure win.
"""

from __future__ import annotations

import json
from typing import Any, Final

from fastapi import APIRouter, HTTPException, Response

from pubg_dashboard.config import REPO_ROOT

router = APIRouter(tags=["tiles"])

TILE_ROOT: Final = REPO_ROOT / "assets" / "maps"
MANIFEST: Final = TILE_ROOT / "manifest.json"

#: Tiles never change for a given map build, so they are cached hard. A
#: re-tile writes the same paths, which is why the manifest is *not* cached —
#: it is how a client notices the build changed.
TILE_CACHE: Final = "public, max-age=31536000, immutable"


@router.get("/tiles/manifest.json")
async def tile_manifest() -> Response:
    """What has been tiled, and the geometry needed to place a dot on it.

    Deliberately not cached: it is the one file that tells a client a re-tile
    happened.
    """
    if not MANIFEST.is_file():
        raise HTTPException(
            404,
            "no tiles built yet — run `uv run scripts/fetch_map_assets.py`",
        )
    data: dict[str, Any] = json.loads(MANIFEST.read_text())
    for name, info in data.items():
        info["tileUrl"] = f"/api/tiles/{name}/{{z}}/{{x}}_{{y}}.webp"
        # px-per-metre is different on every map and must be derived, never
        # hard-coded: Erangel is 8192 px over 8160 m, Camp Jackal 8192 px over
        # 2040 m — a 4x difference from the same image size.
        world_m = info["worldSize"] / 100.0
        info["pxPerMetre"] = info["sourcePx"] * info["imageScale"] / world_m
    return Response(
        content=json.dumps(data),
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/tiles/{map_name}/{zoom}/{tile}")
async def tile(map_name: str, zoom: int, tile: str) -> Response:
    """One 512px webp tile.

    Path components are validated rather than joined blindly: `map_name` and
    `tile` arrive from the URL, and `Path("...") / ".." / ".."` escapes the
    tile root perfectly happily.
    """
    if not tile.endswith(".webp"):
        raise HTTPException(404, "tiles are .webp")
    stem = tile[: -len(".webp")]
    x, _, y = stem.partition("_")
    if not (x.isdigit() and y.isdigit()) or not (0 <= zoom <= 8):
        raise HTTPException(404, "expected {z}/{x}_{y}.webp with non-negative integers")
    if not map_name.replace("_", "").isalnum():
        raise HTTPException(404, "bad map name")

    path = TILE_ROOT / map_name / str(zoom) / f"{int(x)}_{int(y)}.webp"
    # Belt and braces after the component checks above.
    try:
        path.relative_to(TILE_ROOT)
    except ValueError:
        raise HTTPException(404, "not found") from None
    if not path.is_file():
        raise HTTPException(404, f"no tile {map_name}/{zoom}/{x}_{y}")

    return Response(
        content=path.read_bytes(),
        media_type="image/webp",
        headers={"Cache-Control": TILE_CACHE},
    )


def tile_root_exists() -> bool:
    return MANIFEST.is_file()


__all__ = ["router", "tile_root_exists"]
