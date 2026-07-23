"""Frame index and combat tracker, against the archived corpus.

The headline check is `test_corpus_kills_match_the_api_exactly`: telemetry and
the match API are wholly independent descriptions of the same match, so their
agreeing on every participant's kill count is the strongest evidence available
that the parser reads the stream correctly.
"""

from __future__ import annotations

import collections
import itertools
import json
import pathlib
from typing import Any

import pytest

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.frames import (
    DEDUPE_MS,
    FLAG_ALIVE,
    FLAG_DBNO,
    FLAG_DRIVING,
    FLAG_IN_VEHICLE,
    FLAG_PARACHUTING,
    HEAL_MIN_DELTA,
    MAX_HEALTH,
    U16_MAX,
    FrameIndex,
)

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"


def _character(account: str, x: float, y: float, **kw: Any) -> dict[str, Any]:
    return {
        "accountId": account,
        "health": kw.get("health", 100),
        "location": {"x": x, "y": y, "z": 0},
        "isDBNO": kw.get("isDBNO", False),
        "isInVehicle": kw.get("isInVehicle", False),
        "isInBlueZone": kw.get("isInBlueZone", False),
        "isInRedZone": kw.get("isInRedZone", False),
        "teamId": kw.get("teamId", 1),
        "type": kw.get("type", "user"),
    }


def _position(account: str, t: str, x: float, y: float, is_game: float = 1.0, **kw: Any) -> dict:
    return {
        "_T": "LogPlayerPosition",
        "_D": t,
        "character": _character(account, x, y, **kw),
        "common": {"isGame": is_game},
    }


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------


def test_out_of_range_coordinates_clamp_instead_of_wrapping() -> None:
    """Telemetry emits negative x (observed -11623 cm) and above-range values.

    The aircraft flies in from outside the map. Unclamped, `int(round(...))`
    on a negative wraps around the Uint16 and teleports the player to the far
    corner — a plausible-looking dot in entirely the wrong place.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", -11_623.0, 900_000.0))
    arrs = fi.build(["a"], tick_ms=100)
    x = int.from_bytes(arrs.x[0:2], "little")
    y = int.from_bytes(arrs.y[0:2], "little")
    assert x == 0
    assert y == U16_MAX


def test_samples_inside_the_dedupe_window_collapse_to_the_last() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", 1000.0, 1000.0))
    fi.feed(_position("a", "2026-07-22T00:00:00.050Z", 2000.0, 2000.0))
    fi.feed(_position("a", "2026-07-22T00:00:01.000Z", 3000.0, 3000.0))
    assert [s.x for s in fi.samples_for("a")] == [2000.0, 3000.0]
    assert DEDUPE_MS == 100


def test_combat_events_enrich_the_position_track() -> None:
    """`LogPlayerPosition` alone is ~10 s apart; fights need better than that."""
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", 1000.0, 1000.0))
    fi.feed(
        {
            "_T": "LogPlayerAttack",
            "_D": "2026-07-22T00:00:03.000Z",
            "attacker": _character("a", 1500.0, 1500.0),
            "common": {"isGame": 1.0},
        }
    )
    assert fi.positions == 1
    assert fi.enriched == 1
    assert len(fi.samples_for("a")) == 2


def test_kill_event_contributes_positions_for_both_parties() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(
        {
            "_T": "LogPlayerKillV2",
            "_D": "2026-07-22T00:00:03.000Z",
            "victim": _character("v", 1000.0, 1000.0, health=0),
            "killer": _character("k", 2000.0, 2000.0),
            "common": {"isGame": 1.0},
        }
    )
    assert set(fi.accounts()) == {"v", "k"}


def _kill_event(account: str, t: str, x: float = 1.0, y: float = 1.0, **kw: Any) -> dict[str, Any]:
    """A death, for the frames tests. Named apart from the combat section's
    `_kill` below, which shadows anything sharing its name."""
    return {
        "_T": "LogPlayerKillV2",
        "_D": t,
        "victim": _character(account, x, y, health=0, **kw),
        "killer": _character("killer", x, y),
        "common": {"isGame": 1.0},
    }


def test_flags_are_read_from_the_character_block() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", 1.0, 1.0, is_game=0.10000000149011612))
    fi.feed(_position("b", "2026-07-22T00:00:00.000Z", 1.0, 1.0, isDBNO=True, health=0))
    a_flags = fi.samples_for("a")[0].flags
    b_flags = fi.samples_for("b")[0].flags
    assert a_flags & FLAG_PARACHUTING
    assert a_flags & FLAG_ALIVE
    assert b_flags & FLAG_DBNO


def _ride(account: str, t: str, vehicle_type: str) -> dict[str, Any]:
    return {
        "_T": "LogVehicleRide",
        "_D": t,
        "character": _character(account, 1.0, 1.0, isInVehicle=True),
        "vehicle": {"vehicleType": vehicle_type, "vehicleId": "v1"},
        "common": {"isGame": 1.0},
    }


def test_the_match_start_aircraft_is_a_vehicle_but_nobody_is_driving_it() -> None:
    """The trap `FLAG_IN_VEHICLE` alone walks straight into.

    `character.isInVehicle` is true for the **entire lobby** while the plane is
    in the air, and 43% of in-vehicle samples across the corpus are aircraft,
    pickup balloons or a mounted mortar (3,261 of 7,635). A marker keyed on
    `FLAG_IN_VEHICLE` puts a steering wheel on all hundred players before
    anyone has landed.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_ride("a", "2026-07-22T00:00:01.000Z", "TransportAircraft"))
    fi.feed(_position("a", "2026-07-22T00:00:05.000Z", 1.0, 1.0, isInVehicle=True))
    flags = fi.samples_for("a")[-1].flags
    assert flags & FLAG_IN_VEHICLE
    assert not flags & FLAG_DRIVING


@pytest.mark.parametrize(
    ("vehicle_type", "driving"),
    [
        ("WheeledVehicle", True),
        ("FloatingVehicle", True),
        ("FlyingVehicle", True),
        ("TransportAircraft", False),
        ("EmergencyPickup", False),
        ("Mortar", False),
        # Every PUBG enum is open and casing moves between patches, so an
        # unknown type must decline the flag rather than default it on.
        ("SomeVehicleShippedNextPatch", False),
        # ...and a known one must survive a casing change.
        ("wheeledvehicle", True),
    ],
)
def test_only_vehicles_driven_around_the_map_count(vehicle_type: str, driving: bool) -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_ride("a", "2026-07-22T00:00:01.000Z", vehicle_type))
    fi.feed(_position("a", "2026-07-22T00:00:05.000Z", 1.0, 1.0, isInVehicle=True))
    flags = fi.samples_for("a")[-1].flags
    assert bool(flags & FLAG_DRIVING) is driving
    assert flags & FLAG_IN_VEHICLE


def test_leaving_a_vehicle_clears_the_flag_on_that_very_sample() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_ride("a", "2026-07-22T00:00:01.000Z", "WheeledVehicle"))
    fi.feed(_position("a", "2026-07-22T00:00:05.000Z", 1.0, 1.0, isInVehicle=True))
    assert fi.samples_for("a")[-1].flags & FLAG_DRIVING
    fi.feed(
        {
            "_T": "LogVehicleLeave",
            "_D": "2026-07-22T00:00:09.000Z",
            "character": _character("a", 1.0, 1.0, isInVehicle=False),
            "vehicle": {"vehicleType": "WheeledVehicle", "vehicleId": "v1"},
            "common": {"isGame": 1.0},
        }
    )
    assert not fi.samples_for("a")[-1].flags & FLAG_DRIVING


def test_occupancy_comes_from_the_character_not_the_ride_index() -> None:
    """A missed `LogVehicleLeave` must not strand a player in a phantom car.

    The ride index only ever names the vehicle; `isInVehicle` decides whether
    they are in one. Without that gate a dropped dismount would leave the
    marker on for the rest of the match.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_ride("a", "2026-07-22T00:00:01.000Z", "WheeledVehicle"))
    # No leave event — but the character says they are on foot.
    fi.feed(_position("a", "2026-07-22T00:00:20.000Z", 1.0, 1.0, isInVehicle=False))
    flags = fi.samples_for("a")[-1].flags
    assert not flags & FLAG_DRIVING
    assert not flags & FLAG_IN_VEHICLE


def test_a_knocked_player_is_still_flagged_alive() -> None:
    """`health > 0` is not the same question as "still in the match".

    A knocked player reports `health: 0` — 31,153 of 31,156 DBNO snapshots in
    the corpus sit at exactly 0 — so reading the alive bit off health hid every
    knock, and `LogPlayerPosition` keeps firing for a knocked player. In a squad
    fight the knock is most of the story.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("b", "2026-07-22T00:00:00.000Z", 1.0, 1.0, isDBNO=True, health=0))
    flags = fi.samples_for("b")[0].flags
    assert flags & FLAG_ALIVE
    assert flags & FLAG_DBNO


def test_a_kill_clears_both_bits_even_though_the_victim_reads_dbno() -> None:
    """The trap that forces this to be resolved in the parser.

    At `LogPlayerKillV2` the victim's `isDBNO` is **true in 51% of deaths**
    (979 of 1,918 across the corpus). So "alive or knocked" cannot be recovered
    from a sample's own bits — a frontend applying that test would leave half
    of every lobby's corpses on the map forever, as knocked players who never
    get up.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("v", "2026-07-22T00:00:00.000Z", 1.0, 1.0, isDBNO=True, health=0))
    fi.feed(_kill_event("v", "2026-07-22T00:00:05.000Z", isDBNO=True))
    samples = fi.samples_for("v")
    assert samples[0].flags & FLAG_ALIVE, "knocked, still playing"
    assert not samples[-1].flags & FLAG_ALIVE, "dead"
    assert not samples[-1].flags & FLAG_DBNO, "dead, not knocked"


def test_the_last_death_wins_so_a_respawn_is_not_blanked() -> None:
    """Seven players in the corpus died three times.

    Keying on the *first* death would flag them eliminated for the rest of a
    match they are still playing — the same reason `combat` and the inventory
    state machine both key on the last one.

    The stated limit: between an earlier death and the respawn the player still
    reads as in the match. Telemetry has no respawn event, and no archived
    match is a comeback mode, so there is nothing to measure the gap against —
    guessing it would be exactly the plausible-looking invention this parser
    exists to avoid. The final death, which is what removes a player from the
    map, is always right.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_kill_event("v", "2026-07-22T00:00:05.000Z"))
    fi.feed(_position("v", "2026-07-22T00:00:20.000Z", 1.0, 1.0))
    fi.feed(_kill_event("v", "2026-07-22T00:00:30.000Z"))
    samples = fi.samples_for("v")
    # Absolute epoch ms, the same clock as `Sample.t_ms` — which is what
    # `_resolve` compares against.
    assert fi.death_ms("v") == reader.ts_ms("2026-07-22T00:00:30.000Z")
    alive = [bool(s.flags & FLAG_ALIVE) for s in samples]
    assert alive == [True, True, False]


def test_take_damage_health_is_corrected_to_the_value_after_the_shot() -> None:
    """`LogPlayerTakeDamage.victim.health` is the health *before* the damage.

    Measured over the corpus: 1,900 consecutive pairs agree with
    `health - damage`, 134 with `health` unchanged. Stored raw, a player reads
    at their fullest for up to 10 s starting from the instant they are shot —
    which is precisely when someone is watching.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(
        {
            "_T": "LogPlayerTakeDamage",
            "_D": "2026-07-22T00:00:01.000Z",
            "attacker": _character("k", 500.0, 500.0),
            "victim": _character("v", 1000.0, 1000.0, health=90),
            "damage": 62.0,
            "common": {"isGame": 1.0},
        }
    )
    assert fi.samples_for("v")[0].health == pytest.approx(28.0)
    # The attacker's own snapshot is untouched — they were not the one hit.
    assert fi.samples_for("k")[0].health == pytest.approx(100.0)


def test_damage_beyond_remaining_health_clamps_to_zero() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(
        {
            "_T": "LogPlayerTakeDamage",
            "_D": "2026-07-22T00:00:01.000Z",
            "victim": _character("v", 1.0, 1.0, health=12),
            "damage": 100.0,
            "common": {"isGame": 1.0},
        }
    )
    assert fi.samples_for("v")[0].health == 0.0


def test_heal_health_is_corrected_and_ticks_are_thinned() -> None:
    """`LogHeal.character.health` is pre-heal (295 corpus pairs to 2), and the
    event fires per tick — ~4,000 a match, mostly +1 of boost regeneration.

    Keeping all of them cost 40% more samples and 21% more bundle for a bar a
    few pixels tall, so they are thinned on health delta. Thinning on the delta
    rather than on time is what bounds the error: the renderer steps health, and
    each kept sample resets the baseline.
    """
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    for i in range(12):
        fi.feed(
            {
                "_T": "LogHeal",
                # Spread past DEDUPE_MS, so thinning is what is being measured
                # and not the dedupe window.
                "_D": f"2026-07-22T00:00:{i:02d}.000Z",
                "character": _character("a", 1.0, 1.0, health=50 + i),
                "healAmount": 1,
                "common": {"isGame": 1.0},
            }
        )
    healths = [s.health for s in fi.samples_for("a")]
    # First tick is kept unconditionally (no baseline), then every 5 points.
    assert healths == [51.0, 56.0, 61.0]
    assert max(abs(a - b) for a, b in itertools.pairwise(healths)) <= HEAL_MIN_DELTA


def test_health_never_exceeds_full() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(
        {
            "_T": "LogHeal",
            "_D": "2026-07-22T00:00:01.000Z",
            "character": _character("a", 1.0, 1.0, health=98),
            "healAmount": 20,
            "common": {"isGame": 1.0},
        }
    )
    assert fi.samples_for("a")[0].health == MAX_HEALTH


def test_csr_offsets_partition_the_arrays() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    for i in range(3):
        fi.feed(_position("a", f"2026-07-22T00:00:0{i}.000Z", 100.0 * i, 0.0))
    for i in range(2):
        fi.feed(_position("b", f"2026-07-22T00:00:0{i}.000Z", 200.0 * i, 0.0))
    arrs = fi.build(["a", "b"], tick_ms=100)
    off = [int.from_bytes(arrs.off[i : i + 4], "little") for i in range(0, len(arrs.off), 4)]
    assert off == [0, 3, 5]
    assert off[-1] == arrs.n
    assert len(arrs.t) == arrs.n * 2  # Uint16
    assert len(arrs.hp) == arrs.n  # Uint8


def test_player_with_no_samples_gets_an_empty_csr_row() -> None:
    """A disconnect-at-loading player still occupies an index in `players`."""
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", 1.0, 1.0))
    arrs = fi.build(["a", "ghost"], tick_ms=100)
    off = [int.from_bytes(arrs.off[i : i + 4], "little") for i in range(0, len(arrs.off), 4)]
    assert off == [0, 1, 1]


# ---------------------------------------------------------------------------
# combat
# ---------------------------------------------------------------------------


def _kill(victim: str, killer: str | None, *, vteam: int = 1, kteam: int = 2, **kw: Any) -> dict:
    ev: dict[str, Any] = {
        "_T": "LogPlayerKillV2",
        "_D": "2026-07-22T00:00:10.000Z",
        "victim": _character(victim, 100.0, 100.0, teamId=vteam, health=0, **kw),
        "killer": _character(killer, 200.0, 200.0, teamId=kteam) if killer else None,
        "finisher": _character(killer, 200.0, 200.0, teamId=kteam) if killer else None,
        "dBNOMaker": None,
        "killerDamageInfo": {
            "damageCauserName": "WeapHK416_C",
            "damageTypeCategory": "Damage_Gun",
            "damageReason": "HeadShot",
            "distance": 8564.0,
            "isThroughPenetrableWall": False,
        },
        "assists_AccountId": [],
    }
    return ev


def test_zone_death_has_a_null_killer() -> None:
    """`killer` is genuinely null for zone/fall/drown — every read must cope."""
    ct = CombatTracker(t0_s=0.0)
    ct.feed(_kill("v", None))
    assert ct.kills[0].killer_account_id is None
    assert not ct.kills[0].is_suicide


def test_suicide_and_team_kill_do_not_count_as_kills() -> None:
    ct = CombatTracker(t0_s=0.0)
    ct.feed(_kill("v", "v", vteam=1, kteam=1))  # suicide
    ct.feed(_kill("v2", "k", vteam=3, kteam=3))  # team kill
    assert ct.kills[0].is_suicide
    assert ct.kills[1].is_team_kill
    assert ct.players.get("k") is None or ct.players["k"].kills == 0


def test_bot_victims_are_excluded_from_kills_human() -> None:
    """Bots are ~19% of all kills and ~50% of the tracked players' kills.

    Reporting raw `kills` as the headline roughly doubles their K/D.
    """
    ct = CombatTracker(t0_s=0.0)
    ct.feed(_kill("human", "k", type="user"))
    ct.feed(_kill("bot", "k", type="user_ai"))
    assert ct.players["k"].kills == 2
    assert ct.players["k"].kills_human == 1


def test_the_last_death_wins_not_the_first() -> None:
    """A player can die twice — measured: 211 accounts in the corpus, 7 thrice.

    Keying on the first death discards their entire second life and freezes the
    replay's inventory minutes early.
    """
    # t0 is the match start, so `t_s` comes out relative to it.
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    ct = CombatTracker(t0_s=t0)
    first = _kill("v", "k1")
    first["_D"] = "2026-07-22T00:00:10.000Z"
    second = _kill("v", "k2")
    second["_D"] = "2026-07-22T00:20:00.000Z"
    ct.feed(first)
    ct.feed(second)
    death = ct.players["v"].death
    assert death is not None
    assert death.killer_account_id == "k2"
    assert death.t_s == pytest.approx(1200.0)


def test_blue_zone_damage_is_not_attributed_to_a_player() -> None:
    """Most `LogPlayerTakeDamage` events have `attacker = null`."""
    ct = CombatTracker(t0_s=0.0)
    ct.feed(
        {
            "_T": "LogPlayerTakeDamage",
            "_D": "2026-07-22T00:00:05.000Z",
            "attacker": None,
            "victim": _character("v", 1.0, 1.0),
            "damage": 12.5,
            "attackId": -1,
        }
    )
    assert ct.unattributed_damage == pytest.approx(12.5)
    assert not ct.players


def test_longest_kill_ignores_the_minus_one_sentinel() -> None:
    """`distance = -1` means "not applicable"; 8.6% of kills carry it."""
    ct = CombatTracker(t0_s=0.0)
    melee = _kill("v1", "k")
    melee["killerDamageInfo"]["distance"] = -1.0
    real = _kill("v2", "k")
    real["killerDamageInfo"]["distance"] = 15_000.0
    ct.feed(melee)
    ct.feed(real)
    assert ct.longest_kill_cm("k") == pytest.approx(15_000.0)


def test_accuracy_comes_from_all_weapon_stats() -> None:
    """The wire field names are `shots` and `hits` — measured, not documented.

    This test previously asserted `shotsFired` / `hitCount`, matching the
    parser, and passed. Neither name exists in the payload PUBG actually
    sends, so both counters summed to zero for all 5,978 archived
    participants — and because the columns were non-NULL zeros,
    `count(shots_fired)` reported them as fully populated.

    `dBNOHits` is summed into hits: `hits` counts shots that connected with a
    standing target, `dBNOHits` those that connected with a knocked one, and
    accuracy wants both.
    """
    ct = CombatTracker(t0_s=0.0)
    ct.feed(
        {
            "_T": "LogMatchEnd",
            "_D": "2026-07-22T00:30:00.000Z",
            "allWeaponStats": [
                {
                    "accountId": "k",
                    "stats": [
                        {"weapon": "WeapMini14_C", "shots": 63, "hits": 8, "dBNOHits": 0},
                        {"weapon": "WeapMP5K_C", "shots": 99, "hits": 3, "dBNOHits": 2},
                    ],
                },
            ],
        }
    )
    assert ct.players["k"].shots_fired == 162
    assert ct.players["k"].shots_hit == 13


def test_the_old_field_names_are_not_silently_accepted() -> None:
    """A payload using the names the parser used to expect must count zero.

    Guards against someone "restoring" the old spelling as a fallback: an
    `or` chain over both would resurrect the silent-zero bug the moment PUBG
    renamed anything, because a missing key and a zero are indistinguishable
    downstream.
    """
    ct = CombatTracker(t0_s=0.0)
    ct.feed(
        {
            "_T": "LogMatchEnd",
            "_D": "2026-07-22T00:30:00.000Z",
            "allWeaponStats": [
                {"accountId": "k", "stats": [{"shotsFired": 40, "hitCount": 9}]},
            ],
        }
    )
    assert ct.players["k"].shots_fired == 0
    assert ct.players["k"].shots_hit == 0


# ---------------------------------------------------------------------------
# Corpus cross-validation
# ---------------------------------------------------------------------------


def _corpus_pairs(limit: int) -> list[tuple[pathlib.Path, pathlib.Path]]:
    tele, mat = DATA / "telemetry", DATA / "matches"
    if not tele.is_dir() or not mat.is_dir():
        return []
    out = []
    for p in sorted(tele.glob("*.json.gz"))[:limit]:
        m = mat / f"{p.name[: -len('.json.gz')]}.json"
        if m.exists():
            out.append((p, m))
    return out


def test_corpus_kills_match_the_api_exactly() -> None:
    """Telemetry and the match API are independent accounts of the same match.

    Measured over the whole corpus they agree on every participant's kill
    count. Any drift here means the parser has started reading the stream
    differently from how PUBG scored it.
    """
    pairs = _corpus_pairs(20)
    if not pairs:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    agree = 0
    mismatches: list[str] = []
    for tele_path, match_path in pairs:
        stats = {
            inc["attributes"]["stats"]["playerId"]: inc["attributes"]["stats"]
            for inc in json.loads(match_path.read_bytes()).get("included", [])
            if inc["type"] == "participant"
        }
        evs = reader.load(tele_path.read_bytes())
        t0 = next(
            (
                reader.ts(e.get("_D"))
                for e in evs
                if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)
            ),
            0.0,
        )
        ct = CombatTracker(t0)
        for e in evs:
            ct.feed(e)
        for account, api in stats.items():
            mine = ct.players[account].kills if account in ct.players else 0
            if mine == int(api["kills"]):
                agree += 1
            else:
                mismatches.append(f"{account[:16]}: parser={mine} api={api['kills']}")

    assert not mismatches, f"{len(mismatches)} disagreements: {mismatches[:5]}"
    assert agree > 1000


def test_corpus_all_weapon_stats_produce_real_shot_counts() -> None:
    """The regression test the original bug needed.

    The unit test above pins the field names, but a unit test written from the
    same wrong assumption as the code is worth nothing — which is exactly what
    happened. This reads real payloads instead, and fails if the parser ever
    again produces a corpus-wide zero.

    It also pins the coverage limit, because that shapes the UI: PUBG
    populates `allWeaponStats` for only a couple of accounts per match, so
    `shots_fired == 0` must be read as "not reported" and never as "fired
    nothing".
    """
    pairs = _corpus_pairs(20)
    if not pairs:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    total_shots = 0
    total_hits = 0
    covered: list[int] = []
    for tele_path, _ in pairs:
        evs = reader.load(tele_path.read_bytes())
        ct = CombatTracker(0.0)
        for e in evs:
            ct.feed(e)
        with_stats = [p for p in ct.players.values() if p.shots_fired > 0]
        covered.append(len(with_stats))
        total_shots += sum(p.shots_fired for p in with_stats)
        total_hits += sum(p.shots_hit for p in with_stats)

    assert total_shots > 0, "allWeaponStats parsed to zero shots across the corpus"
    # Hits cannot exceed shots, and an accuracy of 100% would mean the two
    # fields have been crossed.
    assert 0 < total_hits < total_shots

    # Measured: a median of 2 accounts per match, never more than 4. If PUBG
    # starts reporting everyone, this fires and the UI can stop apologising.
    assert max(covered) <= 8, f"coverage grew: {covered}"


def test_corpus_double_deaths_are_real_and_common() -> None:
    """BUILD-SPEC says "a player can die twice". The corpus shows three.

    This is the fact that makes `setdefault` on a death the wrong operation.
    """
    pairs = _corpus_pairs(30)
    if not pairs:
        pytest.skip("no archived corpus")
    repeats: collections.Counter[int] = collections.Counter()
    for tele_path, _ in pairs:
        evs = reader.load(tele_path.read_bytes())
        t0 = next(
            (
                reader.ts(e.get("_D"))
                for e in evs
                if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)
            ),
            0.0,
        )
        ct = CombatTracker(t0)
        for e in evs:
            ct.feed(e)
        deaths = collections.Counter(k.victim_account_id for k in ct.kills)
        for n in deaths.values():
            if n > 1:
                repeats[n] += 1
    assert sum(repeats.values()) > 0, "expected repeat deaths somewhere in the corpus"
