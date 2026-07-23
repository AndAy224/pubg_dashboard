"""Zones, care packages, vehicles and the flight path.

**The zone field names are inverted from their meaning.** This is the single
most consequential misreading available in the whole schema, because getting it
backwards produces a replay that looks almost right:

* `safetyZone*` is the **blue** circle — the current damaging boundary.
  Continuous, so **interpolate** between samples.
* `poisonGasWarning*` is the **white** circle — the next circle.
  A step function, so **snap**; interpolating it makes the white circle drift
  across the map instead of jumping.

Corroborated independently by the corpus rather than taken on trust:
`safetyZoneRadius` is high-cardinality continuous, while
`poisonGasWarningRadius` takes exactly 7 discrete values across all 9,771
game-state events — which is what a step function looks like in a histogram.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.reader import norm, ts

__all__ = ["CarePackage", "PlanePath", "VehicleRide", "WorldTracker", "ZoneSample"]

#: A flare-gun vehicle delivery, not a loot crate. It arrives through the same
#: care-package events and would otherwise show up as a crate that contains a car.
FLARE_VEHICLE_PACKAGE: Final = "uaz_armored_c"

#: Spawn and land events share no id — `itemPackageId` is a class name, not an
#: instance. They are paired by nearest **XY** distance; z differs by ~30 km
#: because the spawn is at aircraft altitude, so including z pairs nothing.
CARE_PACKAGE_MAX_PAIR_CM: Final = 50_000.0


@dataclass(slots=True)
class ZoneSample:
    t_s: float
    blue_x: float
    blue_y: float
    blue_r: float
    white_x: float
    white_y: float
    white_r: float
    red_x: float
    red_y: float
    red_r: float
    alive_players: int
    alive_teams: int


@dataclass(slots=True)
class CarePackage:
    spawn_t_s: float | None
    land_t_s: float | None
    x: float
    y: float
    package_id: str
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VehicleRide:
    t_s: float
    account_id: str
    vehicle_id: str
    vehicle_type: str
    x: float
    y: float
    left_t_s: float | None = None
    left_x: float | None = None
    left_y: float | None = None
    ride_distance: float | None = None


@dataclass(slots=True)
class PlanePath:
    """Entry and exit points of the flight line, in centimetres."""

    x0: float
    y0: float
    x1: float
    y1: float


class WorldTracker:
    """Zones, care packages, vehicles and the flight path for one match."""

    __slots__ = (
        "_plane_points",
        "_rides",
        "_spawns",
        "_t0_s",
        "_world_size",
        "landed",
        "phases",
        "rides",
        "zones",
    )

    def __init__(self, t0_s: float, world_size: int) -> None:
        self._t0_s = t0_s
        self._world_size = world_size
        self.zones: list[ZoneSample] = []
        self.phases: list[tuple[float, int]] = []
        self._spawns: list[tuple[float, float, float, str]] = []
        self.landed: list[CarePackage] = []
        self._rides: dict[tuple[str, str], VehicleRide] = {}
        self.rides: list[VehicleRide] = []
        self._plane_points: list[tuple[float, float]] = []

    def _rel(self, event: Mapping[str, Any]) -> float:
        return ts(event.get("_D")) - self._t0_s

    # -- ingest -------------------------------------------------------------
    def feed(self, event: Mapping[str, Any]) -> None:
        kind = norm(event.get("_T", ""))
        if kind == norm(E.GAME_STATE_PERIODIC):
            self._game_state(event)
        elif kind == norm(E.PHASE_CHANGE):
            self.phases.append((self._rel(event), int(event.get("phase") or 0)))
        elif kind == norm(E.CARE_PACKAGE_SPAWN):
            self._package_spawn(event)
        elif kind == norm(E.CARE_PACKAGE_LAND):
            self._package_land(event)
        elif kind == norm(E.VEHICLE_RIDE):
            self._ride(event)
        elif kind == norm(E.VEHICLE_LEAVE):
            self._leave(event)
        elif kind == norm(E.PLAYER_POSITION):
            self._maybe_plane(event)

    def _game_state(self, event: Mapping[str, Any]) -> None:
        gs = event.get("gameState") or {}
        safety = gs.get("safetyZonePosition") or {}
        poison = gs.get("poisonGasWarningPosition") or {}
        red = gs.get("redZonePosition") or {}
        self.zones.append(
            ZoneSample(
                t_s=self._rel(event),
                # safetyZone* -> BLUE. Not a typo; see the module docstring.
                blue_x=float(safety.get("x") or 0.0),
                blue_y=float(safety.get("y") or 0.0),
                blue_r=float(gs.get("safetyZoneRadius") or 0.0),
                # poisonGasWarning* -> WHITE.
                white_x=float(poison.get("x") or 0.0),
                white_y=float(poison.get("y") or 0.0),
                white_r=float(gs.get("poisonGasWarningRadius") or 0.0),
                red_x=float(red.get("x") or 0.0),
                red_y=float(red.get("y") or 0.0),
                # 0 in every archived match — red zones are gone from Erangel.
                # The track is emitted anyway (one line) but the renderer must
                # guard `r > 0` rather than assume it exists.
                red_r=float(gs.get("redZoneRadius") or 0.0),
                alive_players=int(gs.get("numAlivePlayers") or 0),
                alive_teams=int(gs.get("numAliveTeams") or 0),
            )
        )

    def _package_spawn(self, event: Mapping[str, Any]) -> None:
        package = event.get("itemPackage") or {}
        package_id = str(package.get("itemPackageId") or "")
        if norm(package_id) == FLARE_VEHICLE_PACKAGE:
            return
        x, y, _ = E.location(package)
        self._spawns.append((self._rel(event), x, y, package_id))

    def _package_land(self, event: Mapping[str, Any]) -> None:
        package = event.get("itemPackage") or {}
        package_id = str(package.get("itemPackageId") or "")
        if norm(package_id) == FLARE_VEHICLE_PACKAGE:
            return
        x, y, _ = E.location(package)
        items = [
            str(i.get("itemId"))
            for i in (package.get("items") or [])
            if isinstance(i, Mapping) and i.get("itemId")
        ]
        self.landed.append(
            CarePackage(
                spawn_t_s=self._match_spawn(x, y),
                land_t_s=self._rel(event),
                x=x,
                y=y,
                package_id=package_id,
                items=items,
            )
        )

    def _match_spawn(self, x: float, y: float) -> float | None:
        """Nearest unclaimed spawn by XY distance, or None.

        Spawn and land carry no shared identifier, so proximity is the only
        available join. Matching on 3D distance never pairs anything: the spawn
        is recorded at aircraft altitude, ~30 km above the landing point.
        """
        best_i, best_d = -1, CARE_PACKAGE_MAX_PAIR_CM
        for i, (_t, sx, sy, _pid) in enumerate(self._spawns):
            d = math.hypot(sx - x, sy - y)
            if d < best_d:
                best_i, best_d = i, d
        if best_i < 0:
            return None
        t_s = self._spawns.pop(best_i)[0]
        return t_s

    def _ride(self, event: Mapping[str, Any]) -> None:
        character = event.get("character") or {}
        vehicle = event.get("vehicle") or {}
        account = str(character.get("accountId") or "")
        # `vehicleUniqueId` was removed around v17, so there is no instance id
        # to key on. Vehicles are modelled as attached to their occupant: the
        # path is the driver's position chain between ride and leave.
        vehicle_id = str(vehicle.get("vehicleId") or "")
        if not account:
            return
        x, y, _ = E.location(character)
        ride = VehicleRide(
            t_s=self._rel(event),
            account_id=account,
            vehicle_id=vehicle_id,
            vehicle_type=str(vehicle.get("vehicleType") or ""),
            x=x,
            y=y,
        )
        self._rides[(account, vehicle_id)] = ride
        self.rides.append(ride)

    def _leave(self, event: Mapping[str, Any]) -> None:
        character = event.get("character") or {}
        vehicle = event.get("vehicle") or {}
        account = str(character.get("accountId") or "")
        vehicle_id = str(vehicle.get("vehicleId") or "")
        ride = self._rides.pop((account, vehicle_id), None)
        if ride is None:
            return
        x, y, _ = E.location(character)
        ride.left_t_s = self._rel(event)
        ride.left_x = x
        ride.left_y = y
        distance = event.get("rideDistance")
        ride.ride_distance = None if distance is None else float(distance)

    def _maybe_plane(self, event: Mapping[str, Any]) -> None:
        if not E.is_plane_phase((event.get("common") or {}).get("isGame")):
            return
        x, y, _ = E.location(event.get("character") or {})
        self._plane_points.append((x, y))

    # -- output -------------------------------------------------------------
    def plane_path(self) -> PlanePath | None:
        """Fit the flight line by total least squares, extended to map bounds.

        **Not** ordinary least squares. OLS minimises vertical residuals and
        assumes `y = mx + c`, so a north-south flight — where every point
        shares an x — makes the slope explode. Total least squares (the first
        principal component) is rotation invariant and handles it.
        """
        points = self._plane_points
        if len(points) < 2:
            return None

        n = float(len(points))
        mx = sum(p[0] for p in points) / n
        my = sum(p[1] for p in points) / n
        sxx = syy = sxy = 0.0
        for px, py in points:
            dx, dy = px - mx, py - my
            sxx += dx * dx
            syy += dy * dy
            sxy += dx * dy

        # Principal axis of the 2x2 covariance matrix.
        theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
        dir_x, dir_y = math.cos(theta), math.sin(theta)
        if dir_x == 0.0 and dir_y == 0.0:
            return None

        # Orient along travel using the projection of the first and last
        # samples — file order is chronological enough for a direction.
        first = (points[0][0] - mx) * dir_x + (points[0][1] - my) * dir_y
        last = (points[-1][0] - mx) * dir_x + (points[-1][1] - my) * dir_y
        if last < first:
            dir_x, dir_y = -dir_x, -dir_y

        lo, hi = _extend_to_bounds(mx, my, dir_x, dir_y, float(self._world_size))
        return PlanePath(
            x0=mx + dir_x * lo,
            y0=my + dir_y * lo,
            x1=mx + dir_x * hi,
            y1=my + dir_y * hi,
        )

    def blue_circle_at(self, t_s: float) -> tuple[float, float, float] | None:
        """Interpolated blue circle — it shrinks continuously."""
        return _interpolate(self.zones, t_s)

    def white_circle_at(self, t_s: float) -> tuple[float, float, float] | None:
        """**Snapped** white circle. It is a step function; interpolating it
        makes the next circle slide across the map instead of jumping."""
        prev = None
        for z in self.zones:
            if z.t_s > t_s:
                break
            prev = z
        if prev is None:
            return None
        return (prev.white_x, prev.white_y, prev.white_r)


def _interpolate(
    zones: Sequence[ZoneSample], t_s: float
) -> tuple[float, float, float] | None:
    if not zones:
        return None
    if t_s <= zones[0].t_s:
        z = zones[0]
        return (z.blue_x, z.blue_y, z.blue_r)
    for a, b in itertools.pairwise(zones):
        if a.t_s <= t_s <= b.t_s:
            span = b.t_s - a.t_s
            f = 0.0 if span <= 0 else (t_s - a.t_s) / span
            return (
                a.blue_x + (b.blue_x - a.blue_x) * f,
                a.blue_y + (b.blue_y - a.blue_y) * f,
                a.blue_r + (b.blue_r - a.blue_r) * f,
            )
    z = zones[-1]
    return (z.blue_x, z.blue_y, z.blue_r)


def _extend_to_bounds(
    mx: float, my: float, dx: float, dy: float, size: float
) -> tuple[float, float]:
    """Parameter range over which the line stays inside `[0, size]^2`."""
    lo, hi = -1e12, 1e12
    for origin, direction in ((mx, dx), (my, dy)):
        if abs(direction) < 1e-9:
            continue
        t_a = (0.0 - origin) / direction
        t_b = (size - origin) / direction
        lo = max(lo, min(t_a, t_b))
        hi = min(hi, max(t_a, t_b))
    if lo > hi:
        return (0.0, 0.0)
    return (lo, hi)
