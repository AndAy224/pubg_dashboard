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

__all__ = ["FLAG_ALIVE", "FrameArrays", "FrameIndex", "Sample"]

# Flag bits, matching BUILD-SPEC 4.3. The renderer reads these directly.
FLAG_ALIVE: Final = 1 << 0
FLAG_DBNO: Final = 1 << 1
FLAG_IN_VEHICLE: Final = 1 << 2
FLAG_BLUE_ZONE: Final = 1 << 3
FLAG_RED_ZONE: Final = 1 << 4
FLAG_PARACHUTING: Final = 1 << 5

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
}


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


def _flags_from(character: Mapping[str, Any], is_game: float | int | None) -> int:
    flags = 0
    if float(character.get("health") or 0.0) > 0.0:
        flags |= FLAG_ALIVE
    if character.get("isDBNO"):
        flags |= FLAG_DBNO
    if character.get("isInVehicle"):
        flags |= FLAG_IN_VEHICLE
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

    __slots__ = ("_by_account", "_t0_ms", "_world_size", "enriched", "positions")

    def __init__(self, t0_ms: int, world_size: int) -> None:
        self._t0_ms = t0_ms
        self._world_size = world_size
        self._by_account: dict[str, list[Sample]] = {}
        # Split counters so the enrichment's value is measurable rather than
        # asserted — see tests.
        self.positions = 0
        self.enriched = 0

    # -- ingest -------------------------------------------------------------
    def feed(self, event: Mapping[str, Any]) -> None:
        keys = _CHARACTER_KEYS.get(norm(event.get("_T", "")))
        if not keys:
            return
        t_ms = ts_ms(event.get("_D"))
        is_game = (event.get("common") or {}).get("isGame")
        primary = keys[0]
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
            x, y, _z = E.location(character)
            self._by_account.setdefault(account, []).append(
                Sample(
                    t_ms=t_ms,
                    x=x,
                    y=y,
                    health=float(character.get("health") or 0.0),
                    flags=_flags_from(character, is_game),
                )
            )
            if key == primary and norm(event.get("_T", "")) == norm(E.PLAYER_POSITION):
                self.positions += 1
            else:
                self.enriched += 1

    # -- output -------------------------------------------------------------
    def accounts(self) -> list[str]:
        return sorted(self._by_account)

    def samples_for(self, account: str) -> list[Sample]:
        """Time-sorted, deduped samples for one account."""
        return _compact(self._by_account.get(account, []))

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
            for s in _compact(self._by_account.get(account, [])):
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
