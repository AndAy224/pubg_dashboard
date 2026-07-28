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
#: 7 — the parse gained `strategy_rows` (the `strategy_metrics` table: zone
#:     discipline, squad spread, drop, looting and aggression-timing metrics
#:     per participant — see `strategy`), and the drop columns became
#:     trustworthy: `participants.landing_x/y` now come from
#:     `LogParachuteLanding` rather than the first position sample (which can
#:     sit on the aircraft's path), and `landed_at_s` — a column that had
#:     existed unwritten since 0002 — is finally populated.
#: 8 — armor condition. `OP_ARMOR_DESTROY` fired for the first time ever:
#:     `LogArmorDestroy` carries `victim`, not `character`, so the old handler
#:     read an empty account and dropped all 3,316 destroys in the corpus (its
#:     unit test passed on a fixture invented with a `character` field). The
#:     inv track gained `OP_ARMOR_HIT` — per protected hit, with an estimated
#:     remaining-durability percent in `q` (telemetry carries no durability;
#:     see `inventory` rules 11-12 for the fitted model and its two honest
#:     error sources) — and the engine unequip that brackets each destroy is
#:     now suppressed instead of leaking the destroyed piece into `loose`.
#: 9 — `participants.shots_hit` stops double-counting. `_match_end` was adding
#:     `allWeaponStats.dBNOHits` to `hits`, but `dBNOHits` is a **subset** of
#:     `hits`, not an addend — `dBNOHits <= hits` on 547 of 547 weapon rows in
#:     the corpus, and per-weapon derived hit events match `hits` alone at a
#:     median ratio of 1.00 against 0.78 for the sum. Corpus totals: shots
#:     32,821, hits 5,592, dBNOHits 1,757, so **every accuracy figure the
#:     dashboard has ever shown was 31% too high** — 17.0% displayed as 22.4%.
#:     Expect `shots_hit` to *fall* on the 250 participants PUBG reports stats
#:     for; that is the fix, not a regression. Nothing caught it because
#:     `shots_hit` never exceeded `shots_fired` (0 rows of 9,041), so the
#:     number stayed a plausible percentage, and the unit test guarding it was
#:     written from the same assumption as the code — the same shape as the
#:     `shotsFired`/`hitCount` bug in v2 and the `LogArmorDestroy` bug in v8.
#: 10 — accuracy is **derived** instead of copied. `LogPlayerAttack` joined to
#:      `LogPlayerTakeDamage` on `attackId` (throwable attackIds excluded, since
#:      a throw emits both events under one id) reproduces PUBG's own
#:      `allWeaponStats` per weapon at a median ratio of 1.000 for shots
#:      (402 of 531 rows exact) and 1.000 for hits (444 of 453). But PUBG
#:      reports it for a median of 2 accounts per match, so coverage goes from
#:      **3.3% of human participants to 89.9%** — and a zero finally means
#:      "fired nothing" rather than "not reported".
#:
#:      `shots_fired`/`shots_hit` are now **trigger pulls**, not pellets: PUBG
#:      counts 90 shots for 10 Berreta686 attacks, so a pellet-level ratio
#:      reads as several hundred percent accuracy on a shotgun. Pellet-level
#:      hits are kept separately in `hit_events`. PUBG's own numbers move to
#:      `aws_shots`/`aws_hits` and stay there as an oracle.
#:
#:      Adds `participant_weapons` (migration 0006): per account, per weapon,
#:      shots/landed/hits/dbno/headshots/damage. Delete-then-insert, no ledger.
#: 11 — knocks reach SQL, and four values the tracker had always computed and
#:      thrown away are persisted. `knock_events` (migration 0007) is the half
#:      of a squad fight `kill_events` cannot describe: **51% of kill victims
#:      are still flagged `isDBNO` at the moment of death**, so a kill row
#:      credits whoever finished someone, not whoever won the engagement.
#:      Empty is normal — `LogPlayerMakeGroggy` does not exist in solo modes.
#:
#:      On `participants`: `damage_dealt_telemetry` (attacker-attributed only,
#:      so it excludes the blue zone's 63% of damage events, and named apart
#:      from PUBG's own `damage_dealt` because the two will differ),
#:      `blue_zone_damage`, `longest_kill_cm` (already free of the -1
#:      sentinel) and `revives_telemetry`.
#: 12 — **red zones are not gone.** This repo recorded, in four documents, that
#:      they had been removed from Erangel because `LogGameStatePeriodic`'s
#:      `redZone*` fields are 0 in every archived match. The fields are dead;
#:      the feature moved to `LogSpecialZoneInCharacters`, where **19 of 20
#:      matches** carry seven full lifecycles each — Warning, Activating at
#:      +45 s, ActivationDone at ~1 Hz, Deactivating ~30 s later — with a fixed
#:      position, a radius of 395-500 m, and the roster of everyone caught
#:      inside. New `redZones` bundle section, ~200 bytes.
#:
#:      The permanently-zero `zones.rx/ry/rr` arrays are **deleted** rather
#:      than backfilled from it. They are per-sample circles at the game-state
#:      cadence, and resampling a 45 s warning plus a 30 s bombardment into one
#:      radius loses the only distinction that changes behaviour.
#:
#:      Honest limit: red-zone *damage* is negligible — 3 damage events and 1
#:      kill across 15 matches. This is map fidelity and a corrected document,
#:      not a new statistic.
#:
#:      Also: `world.FLARE_VEHICLE_PACKAGE` was the literal `"uaz_armored_c"`,
#:      which occurs **nowhere in the corpus**, so the guard against rendering
#:      flare-gun vehicle deliveries as loot crates caught nothing and 19 of
#:      them showed up as crates. Matched on lowercased substrings now, because
#:      PUBG spells it `Carapackage` in three ids and `Carepackage` in a
#:      fourth. Crates carry `rare` (the red box, 500 of the corpus landings)
#:      and phase events carry `inCircle`, the exact white-circle roster that
#:      `strategy_metrics.rotate_lag_s` approximates with a heuristic.
PARSER_VERSION: Final = 12

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
    red_zones: list[dict[str, Any]]
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
        "redZones": bundle.red_zones,
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
