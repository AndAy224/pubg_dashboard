"""Per-player position track: the thing the replay actually draws.

`LogPlayerPosition` fires roughly every 10 s per player. At 10 s granularity a
firefight is four dots that teleport, so the track is **enriched** from the
`Character` snapshots embedded in combat and vehicle events, which fire exactly
when something is happening. That is what makes fights look right.

Output is CSR (compressed sparse row), not a dict of per-player arrays: one
allocation per field instead of `players x fields` tiny ones, and the renderer's
inner loop keeps a single monotonic cursor per player. Player `p`'s samples are
`[off[p], off[p+1])` in every array.

Samples are **per-player time-sorted and globally interleaved by player** — not
globally time-sorted. That is precisely what makes CSR work.
"""

from __future__ import annotations

import sys
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.reader import norm, ts_ms

__all__ = ["FLAG_ALIVE", "FLAG_DRIVING", "FrameArrays", "FrameIndex", "Sample"]

# Flag bits, matching BUILD-SPEC 4.3. The renderer reads these directly.

#: **Still in the match**, which includes knocked. Resolved in `build()` from
#: each account's *final* death, not from `health > 0`.
#:
#: It used to mean `health > 0`, and that is not the same thing: a knocked
#: player reports `health: 0` (31,156 DBNO snapshots in the corpus, 31,153 of
#: them at exactly 0), so every knocked player was flagged dead and the
#: renderer hid them. The knock is most of the story in a squad fight, and it
#: was invisible — `LogPlayerPosition` keeps firing for a knocked player, so
#: those dots existed and were simply never drawn.
#:
#: The flags cannot be left per-sample for the frontend to combine, either.
#: At `LogPlayerKillV2` the victim's `isDBNO` is **true in 51% of deaths**
#: (979 of 1,918 measured), so "alive or knocked" as a visibility test would
#: leave half of all corpses on the map forever as knocked ghosts. Only the
#: final death time separates the two, and only the parser knows it.
FLAG_ALIVE: Final = 1 << 0

#: Knocked and not yet finished. Cleared at the final death by `build()`.
FLAG_DBNO: Final = 1 << 1
#: In *any* vehicle, straight off `character.isInVehicle`. That includes the
#: match-start aircraft, so this is true for the whole lobby at once.
FLAG_IN_VEHICLE: Final = 1 << 2
FLAG_BLUE_ZONE: Final = 1 << 3
FLAG_RED_ZONE: Final = 1 << 4
FLAG_PARACHUTING: Final = 1 << 5

#: In a vehicle that is **driven around the map** — a car, boat or glider.
#:
#: Distinct from `FLAG_IN_VEHICLE`, and the distinction is most of the point:
#: **43% of in-vehicle samples are not this** (3,261 of 7,635 measured). The
#: match-start aircraft is a vehicle, so `isInVehicle` is true for every player
#: in the lobby for the first minute and a half; so are the flare-gun redeploy
#: plane, the emergency pickup balloon and a mounted mortar.
#:
#: Passengers count. The question is what the vehicle *is*, not who holds the
#: wheel — `seatIndex` is deliberately not consulted.
#:
#: Phase is **not** a usable proxy for this, which is the trap worth recording.
#: Both directions fail: 28 aircraft rides happen mid-match (flare-gun
#: redeploys — `LogParachuteLanding` fires as late as `isGame` 5), and 17 real
#: car rides happen during the plane phase, before `isGame` reaches 1.
FLAG_DRIVING: Final = 1 << 6

#: `vehicle.vehicleType` values that mean "driven around the map", lowercased.
#:
#: Every PUBG enum is open and casing moves between patches, so this is a
#: membership test on a normalised name with a safe default — an unrecognised
#: vehicle simply does not get the flag, rather than the whole lobby getting it
#: because a new aircraft type appeared.
DRIVEN_VEHICLES: Final[frozenset[str]] = frozenset(
    {"wheeledvehicle", "floatingvehicle", "flyingvehicle"}
)

#: Samples closer together than this collapse to one (the last wins). Combat
#: events can emit several snapshots of the same player in the same instant.
DEDUPE_MS: Final = 100

#: Uint16 full scale. Quantisation step is worldSize/65535 = 12.45 cm on an
#: 8x8 km map — half a step of error, invisible where one screen pixel is >= 1 m.
U16_MAX: Final = 65_535

_LITTLE_ENDIAN: Final = sys.byteorder == "little"

# Events carrying a `Character` snapshot, and the keys to look under. These
# fire at combat time, which is exactly where 10 s position sampling is worst.
_CHARACTER_KEYS: Final[dict[str, tuple[str, ...]]] = {
    norm(E.PLAYER_POSITION): ("character",),
    norm(E.PARACHUTE_LANDING): ("character",),
    norm(E.VEHICLE_RIDE): ("character",),
    norm(E.VEHICLE_LEAVE): ("character",),
    norm(E.PLAYER_ATTACK): ("attacker",),
    norm(E.PLAYER_TAKE_DAMAGE): ("attacker", "victim"),
    norm(E.PLAYER_MAKE_GROGGY): ("attacker", "victim"),
    norm(E.PLAYER_REVIVE): ("reviver", "victim"),
    # V2 nests the killer under several roles; all are real Character blocks.
    norm(E.PLAYER_KILL_V2): ("killer", "victim", "finisher", "dBNOMaker"),
    # V1 is absent from the corpus but `combat` keeps a branch for it, so the
    # death index below must see it too or an older archive would leave every
    # victim rendered as permanently knocked.
    norm(E.PLAYER_KILL_V1): ("killer", "victim"),
    # `LogHeal` is the *third* most common event in a match (~4,000 of 37,000)
    # and fires once per heal tick — which is to say, exactly and only when
    # health is changing upwards. Without it a player who bandages from 20 to
    # 100 reads as 20 for up to the full 10 s position interval.
    norm(E.HEAL): ("character",),
}

#: Per-role health adjustment, in points, for events whose `Character` block is
#: a snapshot from *before* the event resolved. See `_health_after`.
#:
#: Measured over the corpus rather than assumed, because both are stated
#: nowhere and both fail plausibly:
#:
#: * `LogPlayerTakeDamage.victim.health` is **pre-damage** — 1,900 consecutive
#:   pairs agree with `health - damage`, 134 with `health`. Fed raw, the dot
#:   shows the health the victim had *before* the shot for up to 10 s, so a
#:   player is at their fullest at the exact instant you watch them get hit.
#: * `LogHeal.character.health` is **pre-heal** — 295 pairs to 2.
_HEALTH_DELTA: Final[dict[tuple[str, str], tuple[str, float]]] = {
    (norm(E.PLAYER_TAKE_DAMAGE), "victim"): ("damage", -1.0),
    (norm(E.HEAL), "character"): ("healAmount", +1.0),
}

#: Health is a percentage; PUBG never reports above this.
MAX_HEALTH: Final = 100.0

#: Heal ticks are only kept once health has moved this far from the previous
#: sample. `LogHeal` fires per tick and most ticks are **+1 point** of boost
#: regeneration, so taking all of them added 40% more samples and 21% to the
#: bundle to animate a bar that is a few pixels tall.
#:
#: Thinning is on the health delta rather than on time, which is what makes the
#: error statable: the renderer steps health rather than interpolating it, and
#: each kept sample resets the baseline, so the drawn value trails the true one
#: by strictly less than this. Damage is never thinned — a hit is the moment
#: the number matters.
HEAL_MIN_DELTA: Final = 5.0


@dataclass(slots=True)
class Sample:
    t_ms: int
    x: float  # centimetres
    y: float  # centimetres
    health: float
    flags: int


@dataclass(slots=True)
class FrameArrays:
    """CSR position index, ready for the bundle writer."""

    n: int
    off: bytes  # Uint32Array[len(players) + 1]
    t: bytes  # Uint16Array[n] — ticks since t0
    x: bytes  # Uint16Array[n] — quantised
    y: bytes  # Uint16Array[n]
    hp: bytes  # Uint8Array[n]
    flags: bytes  # Uint8Array[n]


def _to_le(arr: array) -> bytes:
    """Serialise little-endian regardless of host byte order.

    Every target platform is LE, so this is nearly always a no-op — but the
    bundle records `le: true` and a silent BE write would render as noise
    rather than failing.
    """
    if not _LITTLE_ENDIAN:
        arr = array(arr.typecode, arr)
        arr.byteswap()
    return arr.tobytes()


def _health_after(
    event: Mapping[str, Any], kind: str, key: str, character: Mapping[str, Any]
) -> float:
    """The character's health *after* this event, clamped to 0..100.

    Most events carry a snapshot taken after they resolved. Two do not, and
    both are listed in `_HEALTH_DELTA` with the field to apply.
    """
    health = float(character.get("health") or 0.0)
    adjust = _HEALTH_DELTA.get((kind, key))
    if adjust is not None:
        field, sign = adjust
        health += sign * float(event.get(field) or 0.0)
    return 0.0 if health < 0.0 else min(health, MAX_HEALTH)


def _flags_from(
    character: Mapping[str, Any], is_game: float | int | None, vehicle_type: str | None
) -> int:
    """Per-sample flags. The alive/DBNO bits here are provisional — `build()`
    resolves both against the account's final death.

    `vehicle_type` is what the account was last seen riding, tracked from
    `LogVehicleRide`/`LogVehicleLeave`. The character block says *whether* the
    player is in a vehicle but never *which*, so the two are combined.
    """
    flags = 0
    if float(character.get("health") or 0.0) > 0.0:
        flags |= FLAG_ALIVE
    if character.get("isDBNO"):
        flags |= FLAG_DBNO
    if character.get("isInVehicle"):
        flags |= FLAG_IN_VEHICLE
        # `isInVehicle` gates this deliberately: the ride index is only ever
        # consulted to name the vehicle, never to decide occupancy, so a
        # missed `LogVehicleLeave` cannot strand a player in a phantom car.
        if vehicle_type is not None and norm(vehicle_type) in DRIVEN_VEHICLES:
            flags |= FLAG_DRIVING
    if character.get("isInBlueZone"):
        flags |= FLAG_BLUE_ZONE
    if character.get("isInRedZone"):
        flags |= FLAG_RED_ZONE
    if E.is_plane_phase(is_game):
        flags |= FLAG_PARACHUTING
    return flags


class FrameIndex:
    """Accumulates position samples for one match.

    Feed it every event in the stream; it ignores those it does not recognise.
    """

    __slots__ = (
        "_by_account",
        "_death_ms",
        "_t0_ms",
        "_vehicle",
        "_world_size",
        "enriched",
        "positions",
    )

    def __init__(self, t0_ms: int, world_size: int) -> None:
        self._t0_ms = t0_ms
        self._world_size = world_size
        self._by_account: dict[str, list[Sample]] = {}
        #: Each account's **final** death, for resolving the alive/DBNO bits.
        self._death_ms: dict[str, int] = {}
        #: What each account is currently riding, for `FLAG_DRIVING`. Measured
        #: over the corpus this is complete: every one of the 7,635 in-vehicle
        #: position samples had a preceding ride event, none unknown.
        self._vehicle: dict[str, str] = {}
        # Split counters so the enrichment's value is measurable rather than
        # asserted — see tests.
        self.positions = 0
        self.enriched = 0

    # -- ingest -------------------------------------------------------------
    def feed(self, event: Mapping[str, Any]) -> None:
        kind = norm(event.get("_T", ""))
        keys = _CHARACTER_KEYS.get(kind)
        if not keys:
            return
        t_ms = ts_ms(event.get("_D"))
        is_game = (event.get("common") or {}).get("isGame")
        primary = keys[0]

        if kind in (norm(E.PLAYER_KILL_V2), norm(E.PLAYER_KILL_V1)):
            victim = E.unwrap_character(event.get("victim"))
            account = str((victim or {}).get("accountId") or "")
            # **Latest wins, never `setdefault`.** A player can die twice in
            # comeback modes — seven in the corpus died three times — and
            # keying on the first death would blank them for the rest of a
            # match they are still playing. Same rule `combat` uses.
            if account and t_ms >= self._death_ms.get(account, -1):
                self._death_ms[account] = t_ms

        # Update the ride index **before** building this event's own sample, so
        # the boarding sample already knows the vehicle and the dismount sample
        # no longer does.
        if kind == norm(E.VEHICLE_RIDE):
            rider = E.unwrap_character(event.get("character"))
            account = str((rider or {}).get("accountId") or "")
            if account:
                self._vehicle[account] = str(
                    (event.get("vehicle") or {}).get("vehicleType") or ""
                )
        elif kind == norm(E.VEHICLE_LEAVE):
            rider = E.unwrap_character(event.get("character"))
            account = str((rider or {}).get("accountId") or "")
            if account:
                self._vehicle.pop(account, None)

        for key in keys:
            block = event.get(key)
            if not isinstance(block, Mapping):
                continue
            character = E.unwrap_character(block)
            if not character:
                continue
            account = str(character.get("accountId") or "")
            if not account:
                continue
            health = _health_after(event, kind, key, character)
            track = self._by_account.setdefault(account, [])

            # Thin the heal ticks. Telemetry is time-ordered, so the last
            # appended sample is the baseline to measure against.
            if kind == norm(E.HEAL) and track:
                previous = track[-1]
                if abs(health - previous.health) < HEAL_MIN_DELTA:
                    continue

            x, y, _z = E.location(character)
            track.append(
                Sample(
                    t_ms=t_ms,
                    x=x,
                    y=y,
                    health=health,
                    flags=_flags_from(character, is_game, self._vehicle.get(account)),
                )
            )
            if key == primary and kind == norm(E.PLAYER_POSITION):
                self.positions += 1
            else:
                self.enriched += 1

    # -- output -------------------------------------------------------------
    def accounts(self) -> list[str]:
        return sorted(self._by_account)

    def samples_for(self, account: str) -> list[Sample]:
        """Time-sorted, deduped samples for one account, flags resolved."""
        return self._resolve(account, _compact(self._by_account.get(account, [])))

    def death_ms(self, account: str) -> int | None:
        """The account's final death, or None if it survived."""
        return self._death_ms.get(account)

    def _resolve(self, account: str, samples: list[Sample]) -> list[Sample]:
        """Settle the alive/DBNO bits against the account's final death.

        A sample's own `health`/`isDBNO` cannot answer "is this player still in
        the match": knocked players report health 0, and half of all kill
        victims report `isDBNO: true`. The death time is the only thing that
        separates a knock from a corpse, so it is applied here rather than left
        to the renderer.
        """
        death = self._death_ms.get(account)
        for s in samples:
            if death is not None and s.t_ms >= death:
                # Eliminated: neither alive nor knocked, whatever the snapshot
                # said. This is the sample the renderer stops drawing on.
                s.flags &= ~(FLAG_ALIVE | FLAG_DBNO)
            else:
                # Still in the match — including while knocked, which is when
                # the dot matters most.
                s.flags |= FLAG_ALIVE
        return samples

    def build(self, player_order: list[str], tick_ms: int) -> FrameArrays:
        """Emit the CSR arrays, with rows in `player_order`.

        `player_order` comes from the bundle's `players` list, so index `p`
        means the same thing in every section of the file.
        """
        off = array("I", [0])
        t_arr = array("H")
        x_arr = array("H")
        y_arr = array("H")
        hp_arr = array("B")
        fl_arr = array("B")

        scale = U16_MAX / float(self._world_size)
        max_tick = U16_MAX

        total = 0
        for account in player_order:
            for s in self.samples_for(account):
                tick = (s.t_ms - self._t0_ms) // tick_ms
                # Clamp rather than drop: a pre-t0 event (the aircraft spawns
                # before LogMatchStart) is a real position, and a negative
                # index would wrap to 65535 and put the player in a corner.
                tick = 0 if tick < 0 else (max_tick if tick > max_tick else tick)
                t_arr.append(tick)
                x_arr.append(_quantise(s.x, scale))
                y_arr.append(_quantise(s.y, scale))
                hp = round(s.health)
                hp_arr.append(0 if hp < 0 else (255 if hp > 255 else hp))
                fl_arr.append(s.flags & 0xFF)
                total += 1
            off.append(total)

        return FrameArrays(
            n=total,
            off=_to_le(off),
            t=_to_le(t_arr),
            x=_to_le(x_arr),
            y=_to_le(y_arr),
            hp=_to_le(hp_arr),
            flags=_to_le(fl_arr),
        )


def _quantise(cm: float, scale: float) -> int:
    """cm -> Uint16, clamped into the map.

    Telemetry legitimately emits negative x (observed -11623 cm) and values
    past the world size, because the aircraft flies in from outside the map.
    Unclamped, those wrap around a Uint16 and teleport the player.
    """
    v = round(cm * scale)
    return 0 if v < 0 else (U16_MAX if v > U16_MAX else v)


def _compact(samples: list[Sample]) -> list[Sample]:
    """Sort by time and collapse samples inside one `DEDUPE_MS` window.

    The last sample in a window wins: when a combat event and a routine
    position report land together, the combat one is the more precise account
    of where the player was at that instant.
    """
    if not samples:
        return []
    ordered = sorted(samples, key=lambda s: s.t_ms)
    out: list[Sample] = [ordered[0]]
    for s in ordered[1:]:
        if s.t_ms - out[-1].t_ms < DEDUPE_MS:
            out[-1] = s
        else:
            out.append(s)
    return out
