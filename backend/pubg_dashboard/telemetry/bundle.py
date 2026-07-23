"""The processed-replay bundle: MessagePack, then gzip.

**Why MessagePack and not JSON.** The payload is ~95% numeric arrays.
MessagePack's `bin` type lets the server write a raw little-endian typed-array
buffer that the browser wraps with
`new Uint16Array(buf.buffer, buf.byteOffset, n)` — zero copy, zero parse for
the hot data. JSON would make the main thread parse ~200k numbers into boxed
values on every seek.

All `t` values are Uint16 counts of `tickMs` since `t0`, so a match may not
exceed 65,535 ticks. At the default 100 ms that is 109 minutes against a ~30
minute match; the writer asserts it and falls back to a coarser tick rather
than silently wrapping. **Readers must respect the header's `tickMs`** instead
of assuming 100.
"""

from __future__ import annotations

import gzip
from array import array
from dataclasses import dataclass
from typing import Any, Final

import msgpack

from pubg_dashboard.telemetry.frames import FrameArrays, _to_le

__all__ = ["BUNDLE_VERSION", "PARSER_VERSION", "ReplayBundle", "write_bundle"]

#: Bundle container format. Bump when the *layout* changes.
BUNDLE_VERSION: Final = 1

#: Parser semantics. Bumping this and running `pubgd reparse` re-derives every
#: output from stored raw telemetry with no re-download — which is the entire
#: reason raw telemetry is archived. It is also part of the replay object key,
#: so a bump invalidates cached bundles cleanly.
#: 2 — `allWeaponStats` was read with field names PUBG does not emit
#:     (`shotsFired`/`hitCount`), so `shots_fired` and `shots_hit` were a
#:     silent 0 on every participant. See `combat.CombatPass._match_end`.
#: 3 — `heatmap_bins` gained a `match_type` dimension, so heatmaps can be
#:     filtered to the same match types career stats count. Migration 0003.
#: 4 — the bundle gained a `hits` section: attributed hits with both endpoints,
#:     so the replay can draw combat tracers.
#: 5 — `pos.hp` is now trustworthy, and `pos.flags` means something different.
#:     Three separate faults, all of which rendered plausibly:
#:     (a) `LogPlayerTakeDamage.victim.health` is the health *before* the shot
#:         and was stored raw, so a player read at their fullest for up to 10 s
#:         starting from the instant they were hit;
#:     (b) `LogHeal` was not a health source at all, so healing was invisible;
#:     (c) `FLAG_ALIVE` meant `health > 0`, which is false for every knocked
#:         player, so knocks were hidden — and it cannot be fixed in the
#:         renderer, because 51% of kill victims are flagged `isDBNO` at the
#:         moment of death. `FLAG_ALIVE` now means "still in the match" and is
#:         resolved against each account's final death. See `frames`.
#: 6 — `pos.flags` gained `FLAG_DRIVING`: in a vehicle that is actually driven
#:     around the map. `FLAG_IN_VEHICLE` alone cannot mean that — the
#:     match-start aircraft is a vehicle, so it is set for the entire lobby at
#:     once, and 43% of in-vehicle samples are aircraft, pickup balloons or a
#:     mounted mortar. See `frames.DRIVEN_VEHICLES`.
PARSER_VERSION: Final = 6

DEFAULT_TICK_MS: Final = 100
FALLBACK_TICK_MS: Final = 1000
MAX_TICKS: Final = 65_000  # headroom under the Uint16 ceiling

#: No player index 255 exists in a <=100-player lobby, so it is a safe null.
NULL_PLAYER: Final = 255


@dataclass(slots=True)
class ReplayBundle:
    match_id: str
    shard: str
    map_name: str
    world_size: int
    t0_ms: int
    duration_ms: int
    tick_ms: int
    team_size: int
    weather_id: str
    camera_view: str
    players: list[dict[str, Any]]
    pos: FrameArrays
    events: list[dict[str, Any]]
    zones: dict[str, Any]
    plane: dict[str, float] | None
    inv: dict[str, Any]
    #: Attributed hits, for the replay's combat tracers.
    hits: dict[str, Any]
    dicts: dict[str, list[str]]


def choose_tick_ms(duration_ms: int) -> int:
    """100 ms unless the match is long enough to overflow a Uint16 tick."""
    if duration_ms // DEFAULT_TICK_MS < MAX_TICKS:
        return DEFAULT_TICK_MS
    return FALLBACK_TICK_MS


class Dictionary:
    """Interns strings to small integer indices.

    Weapon and item class names are 30-60 characters and repeat hundreds of
    times per match; storing indices instead turns each into a varint.
    """

    __slots__ = ("_index", "values")

    def __init__(self) -> None:
        self.values: list[str] = []
        self._index: dict[str, int] = {}

    def intern(self, value: str | None) -> int:
        """Index for `value`; `0xFFFF` for absent."""
        if not value:
            return 0xFFFF
        got = self._index.get(value)
        if got is None:
            got = self._index[value] = len(self.values)
            self.values.append(value)
        return got


def quantise(cm: float, world_size: int) -> int:
    """cm -> Uint16, clamped. Same scale as `frames`, so one decoder serves both."""
    v = round(cm / world_size * 65_535)
    return 0 if v < 0 else (65_535 if v > 65_535 else v)


def pack_u16(values: list[int]) -> bytes:
    return _to_le(array("H", [max(0, min(65_535, v)) for v in values]))


def pack_u8(values: list[int]) -> bytes:
    return _to_le(array("B", [max(0, min(255, v)) for v in values]))


def pack_u32(values: list[int]) -> bytes:
    return _to_le(array("I", [max(0, v) for v in values]))


def to_dict(bundle: ReplayBundle) -> dict[str, Any]:
    """Top-level bundle mapping, per BUILD-SPEC 4.1."""
    pos = bundle.pos
    return {
        "v": BUNDLE_VERSION,
        "parserVersion": PARSER_VERSION,
        "matchId": bundle.match_id,
        "shard": bundle.shard,
        # The telemetry mapName, not the display name — the frontend maps it.
        "mapName": bundle.map_name,
        "worldSize": bundle.world_size,
        "t0": bundle.t0_ms,
        "durationMs": bundle.duration_ms,
        "tickMs": bundle.tick_ms,
        "teamSize": bundle.team_size,
        "weatherId": bundle.weather_id,
        "cameraView": bundle.camera_view,
        # Recorded so a future big-endian reader fails loudly instead of
        # rendering noise.
        "le": True,
        "players": bundle.players,
        "pos": {
            "n": pos.n,
            "off": pos.off,
            "t": pos.t,
            "x": pos.x,
            "y": pos.y,
            "hp": pos.hp,
            "flags": pos.flags,
        },
        "events": bundle.events,
        "zones": bundle.zones,
        "plane": bundle.plane,
        "inv": bundle.inv,
        "hits": bundle.hits,
        "dicts": bundle.dicts,
        # NOTE: no `heat` section. BUILD-SPEC 4.1 puts the per-match heatmap
        # deltas in here, but they are server-side bookkeeping for idempotent
        # reparse — the browser cannot use them. Measured on a real match they
        # were 459 KB raw / 48 KB gzipped, **23% of the whole bundle**, which
        # every replay viewer would have downloaded and discarded. (4.7's
        # budget table omits the section entirely, which is presumably how it
        # went unnoticed.) They are written separately by
        # `write_heat_ledger` instead.
    }


def write_heat_ledger(deltas: list[tuple[str, str, str, int, int, int]]) -> bytes:
    """This match's heatmap contribution, for idempotent reparse.

    A reparse must subtract what this match previously added before adding the
    new figures, or every bin double-counts. That requires knowing the old
    contribution, which is what this records. If the ledger is missing, refuse
    to reparse rather than silently inflating the map.

    Stored beside the replay bundle, never inside it.
    """
    return gzip.compress(msgpack.packb(deltas, use_bin_type=True), compresslevel=6)


def read_heat_ledger(raw: bytes) -> list[tuple[str, str, str, int, int, int]]:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return [tuple(row) for row in msgpack.unpackb(raw, raw=False)]


def write_bundle(bundle: ReplayBundle, *, compresslevel: int = 6) -> bytes:
    """Serialise to gzipped MessagePack."""
    packed = msgpack.packb(to_dict(bundle), use_bin_type=True)
    return gzip.compress(packed, compresslevel=compresslevel)


def read_bundle(raw: bytes) -> dict[str, Any]:
    """Inverse of `write_bundle`, for tests and `scripts/replay_dump.py`."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return msgpack.unpackb(raw, raw=False, strict_map_key=False)
