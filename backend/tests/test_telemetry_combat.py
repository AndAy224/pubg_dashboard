"""Frame index and combat tracker, against the archived corpus.

The headline check is `test_corpus_kills_match_the_api_exactly`: telemetry and
the match API are wholly independent descriptions of the same match, so their
agreeing on every participant's kill count is the strongest evidence available
that the parser reads the stream correctly.
"""

from __future__ import annotations

import collections
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
    FLAG_PARACHUTING,
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


def test_flags_are_read_from_the_character_block() -> None:
    fi = FrameIndex(t0_ms=0, world_size=816_000)
    fi.feed(_position("a", "2026-07-22T00:00:00.000Z", 1.0, 1.0, is_game=0.10000000149011612))
    fi.feed(_position("b", "2026-07-22T00:00:00.000Z", 1.0, 1.0, isDBNO=True, health=0))
    a_flags = fi.samples_for("a")[0].flags
    b_flags = fi.samples_for("b")[0].flags
    assert a_flags & FLAG_PARACHUTING
    assert a_flags & FLAG_ALIVE
    assert b_flags & FLAG_DBNO
    assert not b_flags & FLAG_ALIVE


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
