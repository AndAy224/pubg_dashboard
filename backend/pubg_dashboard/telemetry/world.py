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

__all__ = [
    "CarePackage",
    "PhaseChange",
    "PlanePath",
    "RedZone",
    "VehicleRide",
    "WorldTracker",
    "ZoneSample",
    "is_crate_rare",
    "is_flare_vehicle",
]

#: Flare-gun **vehicle** deliveries, not loot crates. They arrive through the
#: same care-package events and would otherwise show up as crates containing a
#: car.
#:
#: This used to be the single literal `"uaz_armored_c"`, which **does not occur
#: anywhere in the corpus** — so the guard caught nothing and 19 vehicle drops
#: were rendered as loot. What actually arrives, counted over the archive:
#:
#:     Carepackage_SmallPackage_NoParachute_Bluechip_C   512
#:     Carapackage_RedBox_C                              500
#:     Carapackage_SmallPackage_NoParachute_C            240
#:     Carapackage_FlareGun_C                             22
#:     BP_BRDM_C                                          16
#:
#: Matched as lowercased **substrings**, never by equality: PUBG spells it
#: `Carapackage` in three of those ids and `Carepackage` in the fourth, and an
#: exact-match list is exactly how the previous version failed silently.
FLARE_VEHICLE_MARKERS: Final = ("uaz_armored", "bp_brdm", "flaregun")

#: Crate rarity, for the replay marker. Substring again, same reason.
CRATE_RARE_MARKER: Final = "redbox"

#: How near a looter has to be to the crate they looted, in centimetres.
#:
#: Measured over 269 pickups: the **worst** distance is 286 cm and the median
#: is 132 — you stand on the crate to loot it. 10 m is therefore generous by a
#: factor of three and still nowhere near the scale of the map.
#:
#: The threshold is not what disambiguates, though. Two crates can land **0 cm
#: apart** (21 pickups had more than one crate within 10 m), so the package
#: name is the real discriminator: the nearest crate's `itemPackageId` matched
#: the pickup's `carePackageName` in 269 of 269 cases.
LOOT_MATCH_MAX_CM: Final = 1_000.0

_RED_ZONE_TYPE: Final = "redzone"
_ZONE_WARNING: Final = "warning"
_ZONE_ACTIVATING: Final = "activating"
_ZONE_DEACTIVATING: Final = "deactivating"


def is_flare_vehicle(package_id: str) -> bool:
    """Is this "care package" actually a flare-gun vehicle delivery?"""
    low = norm(package_id)
    return any(marker in low for marker in FLARE_VEHICLE_MARKERS)


def is_crate_rare(package_id: str) -> bool:
    """The red box — the one worth crossing open ground for."""
    return CRATE_RARE_MARKER in norm(package_id)


@dataclass(slots=True)
class RedZone:
    """One red-zone bombardment: a discrete object, not a per-sample circle.

    **Red zones are not gone.** `LogGameStatePeriodic.redZoneRadius` is 0 in
    every archived match, and this repo concluded from that they had been
    removed from Erangel and that the renderer should not be built. The fields
    are indeed dead; the feature moved to `LogSpecialZoneInCharacters`.

    Measured over the corpus: **19 of 20 matches** carry them, 4,389 events,
    `zoneState` in Warning / Activating / ActivationDone / Deactivating —
    exactly **seven zones per match**, each with a stable `uniqueId` 0..6, a
    position and radius that do not move for the zone's whole life (39,500 to
    50,000 cm, i.e. 395-500 m), and the list of characters caught inside.

    Timing, from one match: Warning, then Activating at **+45 s**, then
    `ActivationDone` repeating at ~1 Hz, then Deactivating **~30 s** later.
    That is the shape a renderer needs and the reason this is not resampled
    into the zone track: the 45 s warning and the 30 s bombardment are
    different states and a single radius array cannot say which is which.

    `unique_id` is **match-scoped** — 0..6 in every match — so it must never
    reach SQL as an identity. It exists to group events within one parse.
    """

    unique_id: int
    x: float
    y: float
    radius: float
    #: Warning issued; the circle is drawn but nothing is falling yet.
    warn_t_s: float
    #: Bombardment starts. None only if the match ended during the warning.
    start_t_s: float | None = None
    #: Bombardment ends. Clamped to the match end by `finalise`, never left
    #: None — an open-ended red zone renders as a bombardment that never stops.
    end_t_s: float | None = None


@dataclass(slots=True)
class PhaseChange:
    """A blue-zone phase step, and who was inside the white circle for it.

    `playersInWhiteCircle` is exact ground truth for the question
    `strategy_metrics.rotate_lag_s` currently answers with a heuristic.

    Each phase **number appears twice** per match, and this docstring used to
    say the first "reports the whole lobby" so the later event should win.
    That is wrong: measured across 8 bundles / 65 phase pairs the first event
    is larger in only **18 of 65**, and its count on a 101-player match is 57.

    The pair is the white-circle **announcement** and the moment the blue
    **starts closing** — 240 s apart for phase 1, then 80/80/80/80/60 s, which
    are PUBG's own zone timings. Both are worth having: "already safe when the
    circle appeared" and "safe when the blue caught up" are different
    questions, and the roster growing between them is players rotating in.

    Two edges when consuming this: phase 1's announcement fires at ~91 s while
    much of the lobby is still airborne over the circle, and a match can end on
    an announcement that never closes — so do not assume pairs.

    `kind` separates the two exactly, from `common.isGame` rather than from the
    gap between them: **`isGame == phase - 0.5` is the announcement and
    `isGame == phase` is the close**, measured with zero exceptions over 362
    events in 23 matches, and the earlier event is the announcement in 178 of
    178 pairs. Phase 1's announcement is the one special case — it carries
    `isGame == 0.1`, the plane phase, which is why its roster is large: the
    lobby is still airborne over the circle.

    What the two instants mean, confirmed from `safetyZone`/`poisonGasWarning`
    radii rather than inferred from the timings:

    * **announce** — the white circle for this phase has appeared. The blue is
      still at the previous phase's radius.
    * **close** — the blue has *started* shrinking toward it (1921 m -> 1835 m
      one sample in). **Not** "finished closing"; the shrink runs on past this.

    So `in_circle` at the close is the rotation deadline — "were we inside by
    the time the blue started moving" — and at the announce it is "were we
    already there when it appeared". Different questions, both worth having.
    """

    t_s: float
    phase: int
    #: `"announce"` or `"close"`. See the class docstring.
    kind: str = "close"
    in_circle: list[str] = field(default_factory=list)

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
    #: `(itemId, stackCount)`. **The count is load-bearing**: a red box holds
    #: three 30-round stacks of 7.62mm, and dropping the counts renders that as
    #: "7.62mm x3" — three bullets instead of ninety, which is a believable
    #: number and the wrong one. Measured across the corpus, ammo stacks are 10
    #: to 90 and boosts/smokes come in twos.
    items: list[tuple[str, int]] = field(default_factory=list)
    #: When someone first took something out of it, or None if nobody did.
    #: Resolved in `finalise_care_packages` — see there for why the join is by
    #: position and package name rather than by an id.
    looted_t_s: float | None = None


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
        "_loots",
        "_open_red",
        "_plane_points",
        "_rides",
        "_spawns",
        "_t0_s",
        "_world_size",
        "landed",
        "phases",
        "red_zones",
        "rides",
        "zones",
    )

    def __init__(self, t0_s: float, world_size: int) -> None:
        self._t0_s = t0_s
        self._world_size = world_size
        self.zones: list[ZoneSample] = []
        self.phases: list[PhaseChange] = []
        self.red_zones: list[RedZone] = []
        # uniqueId -> the zone currently being built. Keyed rather than kept as
        # a single "current", because the Warning of zone N+1 arrives in the
        # same second as the Deactivating of zone N.
        self._open_red: dict[int, RedZone] = {}
        self._spawns: list[tuple[float, float, float, str]] = []
        #: `(t_s, x, y, carePackageName)`, resolved against `landed` at the end.
        self._loots: list[tuple[float, float, float, str]] = []
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
            phase = int(event.get("phase") or 0)
            self.phases.append(
                PhaseChange(
                    t_s=self._rel(event),
                    phase=phase,
                    kind=E.phase_kind(phase, (event.get("common") or {}).get("isGame")),
                    in_circle=[
                        str(a) for a in (event.get("playersInWhiteCircle") or []) if a
                    ],
                )
            )
        elif kind == norm(E.SPECIAL_ZONE_IN_CHARACTERS):
            self._special_zone(event)
        elif kind == norm(E.CARE_PACKAGE_SPAWN):
            self._package_spawn(event)
        elif kind == norm(E.CARE_PACKAGE_LAND):
            self._package_land(event)
        elif kind == norm(E.ITEM_PICKUP_FROM_CAREPACKAGE):
            character = event.get("character") or {}
            x, y, _ = E.location(character)
            self._loots.append((self._rel(event), x, y, str(event.get("carePackageName") or "")))
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
                # 0 in every archived match — but **red zones are not gone**,
                # these fields are simply dead. The feature lives in
                # `LogSpecialZoneInCharacters`; see `RedZone`. Kept here only
                # so the game-state shape stays a faithful mirror of the wire.
                # Nothing reads them, and they are no longer in the bundle.
                red_r=float(gs.get("redZoneRadius") or 0.0),
                alive_players=int(gs.get("numAlivePlayers") or 0),
                alive_teams=int(gs.get("numAliveTeams") or 0),
            )
        )

    def _package_spawn(self, event: Mapping[str, Any]) -> None:
        package = event.get("itemPackage") or {}
        package_id = str(package.get("itemPackageId") or "")
        if is_flare_vehicle(package_id):
            return
        x, y, _ = E.location(package)
        self._spawns.append((self._rel(event), x, y, package_id))

    def _package_land(self, event: Mapping[str, Any]) -> None:
        package = event.get("itemPackage") or {}
        package_id = str(package.get("itemPackageId") or "")
        if is_flare_vehicle(package_id):
            return
        x, y, _ = E.location(package)
        items = [
            (str(i.get("itemId")), int(i.get("stackCount") or 1))
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

    def _special_zone(self, event: Mapping[str, Any]) -> None:
        """Build red-zone lifecycles from `LogSpecialZoneInCharacters`.

        Dispatch is on the **lowercased** zone type and state, with no
        exhaustive branch: every PUBG enum is open and casing has moved between
        patches for all of them. An unrecognised zone type is ignored rather
        than assumed to be a red zone.
        """
        info = event.get("zoneInfo") or {}
        if norm(str(info.get("zoneType") or "")) != _RED_ZONE_TYPE:
            return
        state = norm(str(info.get("zoneState") or ""))
        unique_id = int(info.get("uniqueId") or 0)
        t = self._rel(event)

        if state == _ZONE_WARNING:
            position = info.get("position") or {}
            self._open_red[unique_id] = RedZone(
                unique_id=unique_id,
                x=float(position.get("x") or 0.0),
                y=float(position.get("y") or 0.0),
                # Position and radius do not move for the zone's whole life,
                # so they are taken once at the warning rather than tracked.
                radius=float(info.get("horizontalRadius") or 0.0),
                warn_t_s=t,
            )
            return

        zone = self._open_red.get(unique_id)
        if zone is None:
            # A zone whose Warning was never seen — a truncated stream, or a
            # match joined late. Better to drop it than to invent a start.
            return
        if state == _ZONE_ACTIVATING and zone.start_t_s is None:
            zone.start_t_s = t
        elif state == _ZONE_DEACTIVATING:
            zone.end_t_s = t
            self.red_zones.append(zone)
            del self._open_red[unique_id]

    def finalise_care_packages(self) -> None:
        """Mark each crate with the first time anyone took something from it.

        **There is no id to join on.** `LogItemPickupFromCarepackage` carries a
        `carePackageUniqueId`, but `LogCarePackageLand` does not carry it or
        anything else identifying — its `itemPackage` has exactly
        `itemPackageId`, `items` and `location` — and the pickup's uniqueId is
        a small per-match sequence (0-4) that means nothing on its own.

        So the join is position plus package name, and both parts are needed:
        the looter is within 286 cm of the crate in the worst observed case,
        but two crates can land **0 cm apart**, and the nearest crate's
        `itemPackageId` matched the pickup's `carePackageName` in 269 of 269
        measured pickups.

        Stated limit: two crates of the *same type* stacked on the same spot
        cannot be told apart, and the earlier one wins. They are also drawn on
        top of each other, so the picture is right either way.

        Resolved after the pass rather than during it, so nothing depends on a
        pickup arriving after its land event.
        """
        for t_s, x, y, name in self._loots:
            best: CarePackage | None = None
            best_d = LOOT_MATCH_MAX_CM
            for cp in self.landed:
                if name and cp.package_id != name:
                    continue
                d = math.hypot(cp.x - x, cp.y - y)
                if d < best_d:
                    best, best_d = cp, d
            if best is None:
                continue
            if best.looted_t_s is None or t_s < best.looted_t_s:
                best.looted_t_s = t_s

    def finalise_red_zones(self, duration_s: float) -> None:
        """Close any zone still open when the stream ended.

        A match that ends mid-bombardment leaves `end_t_s` unset, and an
        open-ended red zone renders as a bombardment that never stops — which
        looks like a long fight rather than like missing data.
        """
        for zone in self._open_red.values():
            zone.end_t_s = duration_s
            if zone.start_t_s is None:
                zone.start_t_s = min(zone.warn_t_s, duration_s)
            self.red_zones.append(zone)
        self._open_red.clear()
        self.red_zones.sort(key=lambda z: z.warn_t_s)

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
