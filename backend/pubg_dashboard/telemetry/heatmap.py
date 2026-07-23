"""Spatial bin accumulation.

A 256x256 grid per (map, kind, account, mode, day). Each observation increments
**four** rows, not one: the cross product of {this player, all players} with
{this mode, all modes}. Precomputing all four is what lets
`/api/heatmap?accountId=&gameMode=` answer every filter combination with a
single indexed read instead of a scan.

The `''` sentinels are load-bearing rather than lazy. `heatmap_bins` has them
in its primary key, and in Postgres `NULL != NULL`, so nullable "all" columns
would make `ON CONFLICT DO UPDATE` never fire: every reparse would append a
fresh duplicate set of global bins and silently inflate the heatmap without
ever erroring.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.reader import norm

__all__ = ["GRID", "KINDS", "HeatmapAccumulator"]

GRID: Final = 256

KIND_KILL: Final = "kill"
KIND_DEATH: Final = "death"
KIND_KNOCK: Final = "knock"
KIND_LANDING: Final = "landing"
KIND_MOVEMENT: Final = "movement"
KIND_CARE_PACKAGE: Final = "care_package"
KIND_VEHICLE_DESTROY: Final = "vehicle_destroy"

KINDS: Final[tuple[str, ...]] = (
    KIND_KILL,
    KIND_DEATH,
    KIND_KNOCK,
    KIND_LANDING,
    KIND_MOVEMENT,
    KIND_CARE_PACKAGE,
    KIND_VEHICLE_DESTROY,
)

#: "every player" / "every mode".
ALL: Final = ""

# Bin key: (kind, account_id, game_mode, grid_x, grid_y)
_BinKey = tuple[str, str, str, int, int]


class HeatmapAccumulator:
    """Bins one match's observations, then emits upsertable rows."""

    __slots__ = (
        "_bins",
        "_day",
        "_game_mode",
        "_map_name",
        "_match_type",
        "_world_size",
        "skipped",
    )

    def __init__(
        self,
        *,
        map_name: str,
        game_mode: str,
        day: dt.date,
        world_size: int,
        match_type: str = "official",
    ) -> None:
        self._map_name = map_name
        self._game_mode = game_mode
        self._day = day
        self._world_size = world_size
        # Not part of the cross product: every observation in one match shares
        # the match's type, so it is a constant on the row rather than a
        # dimension to expand. "All types" is a query that omits the filter.
        self._match_type = match_type
        self._bins: dict[_BinKey, int] = {}
        #: Observations dropped for having no usable position.
        self.skipped = 0

    # -- binning ------------------------------------------------------------
    def _bin(self, coord: float) -> int:
        """Clamp **then** scale.

        A single out-of-range aircraft position would otherwise index past the
        grid. Clamping to `world_size - 1` (not `world_size`) keeps the result
        strictly inside `0..GRID-1`.
        """
        if coord < 0.0:
            coord = 0.0
        limit = float(self._world_size - 1)
        if coord > limit:
            coord = limit
        return int(coord / self._world_size * GRID)

    def add(self, kind: str, x: float, y: float, account_id: str, *, count: int = 1) -> None:
        """Record one observation at `(x, y)` centimetres."""
        gx, gy = self._bin(x), self._bin(y)
        # The cross product: (player, mode), (player, all), (all, mode), (all, all).
        for account in {account_id, ALL}:
            for mode in {self._game_mode, ALL}:
                key = (kind, account, mode, gx, gy)
                self._bins[key] = self._bins.get(key, 0) + count

    # -- stream ingest ------------------------------------------------------
    def feed(self, event: Mapping[str, Any]) -> None:
        """Handle the kinds derived straight from the event stream.

        `kill`, `death` and `knock` come from the combat tracker instead, so
        that the heatmap and `kill_events` can never disagree about where a
        kill happened.
        """
        kind = norm(event.get("_T", ""))

        if kind == norm(E.PLAYER_POSITION):
            # Movement excludes the plane phase. Include it and every heatmap
            # shows the flight line rather than where people go — and it still
            # looks like a heatmap.
            if not E.is_in_play((event.get("common") or {}).get("isGame")):
                return
            character = event.get("character") or {}
            account = str(character.get("accountId") or "")
            if not account:
                self.skipped += 1
                return
            x, y, _ = E.location(character)
            self.add(KIND_MOVEMENT, x, y, account)

        elif kind == norm(E.PARACHUTE_LANDING):
            character = event.get("character") or {}
            account = str(character.get("accountId") or "")
            x, y, _ = E.location(character)
            if account:
                self.add(KIND_LANDING, x, y, account)
            else:
                self.skipped += 1

        elif kind == norm(E.CARE_PACKAGE_LAND):
            package = event.get("itemPackage") or {}
            x, y, _ = E.location(package)
            # Care packages belong to nobody, so only the global row is real.
            self.add(KIND_CARE_PACKAGE, x, y, ALL)

        elif kind == norm(E.VEHICLE_DESTROY):
            attacker = event.get("attacker") if isinstance(event.get("attacker"), Mapping) else None
            account = str(attacker.get("accountId") or "") if attacker else ALL
            x, y, _ = E.location(event.get("vehicle") or {})
            self.add(KIND_VEHICLE_DESTROY, x, y, account)

    # -- output -------------------------------------------------------------
    def rows(self) -> list[dict[str, Any]]:
        """Rows for `INSERT ... ON CONFLICT DO UPDATE SET count = count + EXCLUDED.count`."""
        return [
            {
                "map_name": self._map_name,
                "kind": kind,
                "account_id": account,
                "game_mode": mode,
                "match_type": self._match_type,
                "day": self._day,
                "grid_x": gx,
                "grid_y": gy,
                "count": count,
            }
            for (kind, account, mode, gx, gy), count in sorted(self._bins.items())
        ]

    def deltas(self) -> list[tuple[str, str, str, int, int, int]]:
        """This match's contribution, for the server-side reparse ledger.

        A reparse must **subtract what this match previously added before
        adding the new figures**, or every bin double-counts. Recording the
        deltas is what makes that possible without a per-match bin table. If
        the ledger is missing, refuse to reparse rather than silently
        inflating the map.

        Written by `bundle.write_heat_ledger` and stored *beside* the replay
        bundle, not inside it: the browser cannot use these, and on a real
        match they were 23% of the bundle's compressed size.
        """
        return [
            (kind, account, mode, gx, gy, count)
            for (kind, account, mode, gx, gy), count in sorted(self._bins.items())
        ]

    def __len__(self) -> int:
        return len(self._bins)
