"""Reading the place-name artifacts built by `scripts/build_gazetteer.py`.

PUBG ships its own place names in every `Character.zone`, but the one event
that says where a player dropped — `LogParachuteLanding` — carries a zone only
~1.2% of the time. So the names are harvested from the events that do carry
them, binned to the same 256x256 grid `heatmap_bins` uses, and looked up
afterwards. That build is offline and its output is committed; this module only
reads it.

The artifacts are a **static fact about a map**, not an accumulating aggregate.
See the script's docstring for why that distinction is load-bearing: a table
filled at parse time would double its support on every reparse and the modal
name would still look right.
"""

from __future__ import annotations

import functools
import json
import math
import pathlib
from typing import Any, Final, NamedTuple

__all__ = ["Gazetteer", "PlaceLabel", "available_maps", "load_gazetteer"]

PLACES_DIR: Final = pathlib.Path(__file__).parent / "places"


class PlaceLabel(NamedTuple):
    """What a point is called, and how confident that is.

    `name` is None when no named cell is within range. That is the normal case,
    not an error: only ~9% of the grid carries a name, so a drop in open
    country genuinely has no place name and the caller is expected to say so
    rather than reach for the nearest one regardless of distance.
    """

    name: str | None
    #: Metres from the query point to the cell that supplied the name. None
    #: when `name` is None.
    distance_m: float | None
    #: The nearest named place at any distance, for an honest "1.4 km NW of
    #: Gatka" fallback. None only when the map has no gazetteer at all.
    nearest: str | None
    nearest_distance_m: float | None


class Gazetteer:
    """Named grid cells for one map, with a nearest-name lookup."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self.map_name: str = doc["map"]
        self.grid: int = doc["grid"]
        self.world_size: int = doc["worldSize"]
        self.names: list[str] = doc["names"]
        self.built_from: dict[str, Any] = doc.get("builtFrom", {})
        #: (gx, gy) -> (name index, support)
        self.cells: dict[tuple[int, int], tuple[int, int]] = {
            (c[0], c[1]): (c[2], c[3]) for c in doc["cells"]
        }
        self._cell_m = self.world_size / self.grid / 100.0

    def cell_of(self, x_cm: float, y_cm: float) -> tuple[int, int]:
        """Grid cell for a centimetre coordinate.

        Clamped, not wrapped: `y` is **not** inverted here or anywhere (origin
        top-left, y grows downward), and a coordinate a few centimetres outside
        the world is a rounding artefact rather than a reason to raise.
        """
        gx = min(self.grid - 1, max(0, int(x_cm * self.grid / self.world_size)))
        gy = min(self.grid - 1, max(0, int(y_cm * self.grid / self.world_size)))
        return gx, gy

    def label(self, x_cm: float, y_cm: float, within_m: float = 150.0) -> PlaceLabel:
        """Name the point, and always report the nearest place regardless.

        Searches outward by grid ring rather than scanning all 5,700 cells: the
        answer is almost always in the first ring, and the drop endpoint calls
        this once per cluster.
        """
        if not self.cells:
            return PlaceLabel(None, None, None, None)

        gx, gy = self.cell_of(x_cm, y_cm)
        best_name: str | None = None
        best_d = math.inf
        # Ring radius in cells needed to cover the whole grid from any corner.
        for radius in range(self.grid):
            found_this_ring = False
            for cx, cy in _ring(gx, gy, radius, self.grid):
                hit = self.cells.get((cx, cy))
                if hit is None:
                    continue
                found_this_ring = True
                # Distance between cell centres, which is the resolution this
                # data actually has — a sub-cell figure would be invented
                # precision.
                d = math.dist((gx + 0.5, gy + 0.5), (cx + 0.5, cy + 0.5)) * self._cell_m
                if d < best_d:
                    best_d, best_name = d, self.names[hit[0]]
            # One ring past the first hit, because a diagonal cell in ring r+1
            # can be closer than an orthogonal one in ring r.
            if found_this_ring and best_name is not None and radius * self._cell_m > best_d:
                break

        if best_name is None:
            return PlaceLabel(None, None, None, None)
        within = best_name if best_d <= within_m else None
        return PlaceLabel(within, best_d if within else None, best_name, best_d)


def _ring(gx: int, gy: int, radius: int, grid: int) -> list[tuple[int, int]]:
    """Cells exactly `radius` steps from (gx, gy), Chebyshev, clipped to grid."""
    if radius == 0:
        return [(gx, gy)] if 0 <= gx < grid and 0 <= gy < grid else []
    out: list[tuple[int, int]] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            if max(abs(dx), abs(dy)) != radius:
                continue
            cx, cy = gx + dx, gy + dy
            if 0 <= cx < grid and 0 <= cy < grid:
                out.append((cx, cy))
    return out


@functools.lru_cache(maxsize=16)
def load_gazetteer(map_name: str) -> Gazetteer | None:
    """The gazetteer for a map, or None if none has been built.

    None is a real answer, and callers must not dress it up: a map played once
    and not yet in `data/telemetry` genuinely has no names, and saying "no
    gazetteer built for Desert_Main" is useful where "not found" is not.
    """
    path = PLACES_DIR / f"{map_name.lower()}.json"
    if not path.is_file():
        return None
    return Gazetteer(json.loads(path.read_text()))


def available_maps() -> list[str]:
    """Map names with a built gazetteer, from the artifacts on disk."""
    if not PLACES_DIR.is_dir():
        return []
    out = []
    for path in sorted(PLACES_DIR.glob("*.json")):
        try:
            out.append(json.loads(path.read_text())["map"])
        except (OSError, ValueError, KeyError):
            continue
    return out
