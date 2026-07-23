"""Strategy metrics: zone discipline, squad spread, drop, looting, aggression.

Synthetic cases pin each rule; the corpus cases check the rules against real
matches, because a fixture written from the same assumptions as the code is
not evidence about a wire format.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import statistics

import pytest

from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.frames import FLAG_ALIVE, FrameIndex
from pubg_dashboard.telemetry.inventory import InventoryTracker
from pubg_dashboard.telemetry.parse import parse_telemetry
from pubg_dashboard.telemetry.strategy import (
    DWELL_CAP_S,
    WHITE_R_PLACEHOLDER_CM,
    compute_strategy,
)
from pubg_dashboard.telemetry.world import WorldTracker

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
WORLD = 816_000
T0 = "2026-07-22T00:00:00.000Z"
T0_MS = reader.ts_ms(T0)


def _at(seconds: float) -> str:
    ms = int(seconds * 1000)
    return f"2026-07-22T00:{ms // 60000:02d}:{(ms % 60000) // 1000:02d}.{ms % 1000:03d}Z"


def _pos(
    t_s: float,
    account: str,
    x: float,
    y: float,
    *,
    blue: bool = False,
    team: int = 1,
) -> dict:
    return {
        "_T": "LogPlayerPosition",
        "_D": _at(t_s),
        "character": {
            "accountId": account,
            "name": account,
            "teamId": team,
            "type": "user",
            "health": 100,
            "isDBNO": False,
            "isInVehicle": False,
            "isInBlueZone": blue,
            "isInRedZone": False,
            "location": {"x": x, "y": y, "z": 0},
        },
        "common": {"isGame": 1.0},
        "elapsedTime": int(t_s),
        "numAlivePlayers": 50,
    }


def _landing(t_s: float, account: str, x: float, y: float, *, team: int = 1) -> dict:
    return {
        "_T": "LogParachuteLanding",
        "_D": _at(t_s),
        "character": {
            "accountId": account,
            "name": account,
            "teamId": team,
            "type": "user",
            "health": 100,
            "isDBNO": False,
            "isInVehicle": False,
            "isInBlueZone": False,
            "isInRedZone": False,
            "location": {"x": x, "y": y, "z": 0},
        },
        "common": {"isGame": 1.0},
        "distance": 100.0,
    }


def _gamestate(t_s: float, *, white: tuple[float, float, float]) -> dict:
    return {
        "_T": "LogGameStatePeriodic",
        "_D": _at(t_s),
        "gameState": {
            "safetyZonePosition": {"x": 0, "y": 0, "z": 0},
            "safetyZoneRadius": 400_000,
            "poisonGasWarningPosition": {"x": white[0], "y": white[1], "z": 0},
            "poisonGasWarningRadius": white[2],
            "redZonePosition": {"x": 0, "y": 0, "z": 0},
            "redZoneRadius": 0,
            "numAlivePlayers": 50,
            "numAliveTeams": 13,
        },
    }


def _compute(
    events: list[dict], teams: dict[str, int]
) -> dict[str, dict]:
    frames = FrameIndex(T0_MS, WORLD)
    world = WorldTracker(T0_MS / 1000.0, WORLD)
    combat = CombatTracker(T0_MS / 1000.0)
    inventory = InventoryTracker(T0_MS)
    for e in events:
        inventory.prescan(e)
    state: dict = {}
    for e in events:
        frames.feed(e)
        world.feed(e)
        combat.feed(e)
        inventory.feed(e, state)
    rows = compute_strategy(
        match_id="m1",
        frames=frames,
        world=world,
        combat=combat,
        inventory=inventory,
        teams=teams,
        t0_ms=T0_MS,
    )
    return {r["account_id"]: r for r in rows}


# ---------------------------------------------------------------------------
# zone discipline
# ---------------------------------------------------------------------------


def test_blue_dwell_counts_flagged_gaps_and_clamps_sparse_ones() -> None:
    """A 90 s hole in the track books DWELL_CAP_S, not 90 s of blue."""
    a = "account.a"
    events = [
        _landing(60, a, 1000, 1000),
        _pos(100, a, 1000, 1000, blue=True),
        _pos(110, a, 1000, 1000, blue=True),
        _pos(200, a, 1000, 1000, blue=False),
        _pos(210, a, 1000, 1000, blue=False),
    ]
    rows = _compute(events, {a: 1})
    assert rows[a]["blue_s"] == pytest.approx(10.0 + DWELL_CAP_S)


def test_blue_dwell_gates_on_landing() -> None:
    """Blue-flagged samples during the flight are not zone indiscipline."""
    a = "account.a"
    before = [_pos(20, a, 1000, 1000, blue=True), _pos(30, a, 1000, 1000, blue=True)]
    rows = _compute([*before, _landing(60, a, 1000, 1000)], {a: 1})
    assert rows[a]["blue_s"] == 0.0

    # And with no landing at all, the metric is unmeasurable, not zero.
    rows = _compute(before, {a: 1})
    assert rows[a]["blue_s"] is None


def test_rotate_lag_clock_starts_at_landing_when_announced_earlier() -> None:
    """The first circle is usually announced while players are still airborne;
    nobody can rotate from the aircraft, so the clock starts at landing."""
    a = "account.a"
    events = [
        _gamestate(50, white=(0, 0, 100_000)),
        _landing(100, a, 500_000, 0),
        _pos(150, a, 50_000, 0),  # inside the announced circle
    ]
    rows = _compute(events, {a: 1})
    assert rows[a]["rotate_lag_s"] == pytest.approx(50.0)


def test_rotate_lag_ignores_the_pregame_placeholder_circle() -> None:
    a = "account.a"
    events = [
        _gamestate(10, white=(0, 0, WHITE_R_PLACEHOLDER_CM + 50_000)),
        _landing(60, a, 1000, 1000),
        _pos(70, a, 1000, 1000),
    ]
    rows = _compute(events, {a: 1})
    assert rows[a]["rotate_lag_s"] is None


# ---------------------------------------------------------------------------
# squad spread
# ---------------------------------------------------------------------------


def test_teammate_spread_uses_nearest_living_teammate() -> None:
    a, b = "account.a", "account.b"
    events = [
        _landing(60, a, 0, 0),
        _landing(60, b, 0, 5_000),
        _pos(100, a, 0, 0),
        _pos(101, b, 0, 5_000),  # 50 m apart
        _pos(110, a, 0, 0),
        _pos(111, b, 0, 25_000),  # 250 m apart
    ]
    rows = _compute(events, {a: 1, b: 1})
    # Three pairings: the landing samples at t=60 (50 m), then t=100 (50 m),
    # then t=110 against b's nearest-in-time sample at t=111 (250 m) — not
    # b's *spatially closer* sample at t=101.
    assert rows[a]["teammate_dist_avg_cm"] == pytest.approx((5_000 + 5_000 + 25_000) / 3)
    assert rows[a]["teammate_near_pct"] == pytest.approx(2 / 3)


def test_solo_has_no_spread_metrics() -> None:
    a, b = "account.a", "account.b"
    events = [
        _landing(60, a, 0, 0),
        _landing(60, b, 0, 5_000, team=2),
        _pos(100, a, 0, 0),
        _pos(101, b, 0, 5_000, team=2),
    ]
    rows = _compute(events, {a: 1, b: 2})
    assert rows[a]["teammate_dist_avg_cm"] is None
    assert rows[a]["teammate_near_pct"] is None


# ---------------------------------------------------------------------------
# drop
# ---------------------------------------------------------------------------


def test_hot_drop_counts_offteam_landings_nearby() -> None:
    a, b, c, d = "account.a", "account.b", "account.c", "account.d"
    events = [
        _landing(60, a, 0, 0),
        _landing(70, b, 10_000, 0, team=1),  # teammate: never counted
        _landing(80, c, 15_000, 0, team=2),  # 150 m, 20 s later: counted
        _landing(90, d, 500_000, 0, team=3),  # 5 km away: not counted
    ]
    rows = _compute(events, {a: 1, b: 1, c: 2, d: 3})
    assert rows[a]["hot_drop_n"] == 1
    assert rows[c]["hot_drop_n"] == 2  # a and b both landed on c


# ---------------------------------------------------------------------------
# looting
# ---------------------------------------------------------------------------


def test_first_weapon_is_measured_from_landing() -> None:
    a = "account.a"
    weapon = {
        "itemId": "Item_Weapon_M416_C",
        "category": "Weapon",
        "subCategory": "Main",
        "stackCount": 1,
        "attachedItems": [],
    }
    events = [
        _landing(60, a, 0, 0),
        {"_T": "LogItemPickup", "_D": _at(70), "character": {"accountId": a}, "item": weapon},
        {"_T": "LogItemEquip", "_D": _at(72), "character": {"accountId": a}, "item": weapon},
    ]
    rows = _compute(events, {a: 1})
    assert rows[a]["first_weapon_s"] == pytest.approx(12.0)
    assert rows[a]["early_pickups_n"] == 1


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------


def _corpus() -> list[tuple[pathlib.Path, dict]]:
    """Official matches only. The smallest telemetry file overall is a
    training-range match with a two-person roster, which makes every
    percentage assertion below degenerate."""
    tele, mat = DATA / "telemetry", DATA / "matches"
    if not tele.is_dir() or not mat.is_dir():
        return []
    out = []
    for p in sorted(tele.glob("*.json.gz")):
        m = mat / f"{p.name[: -len('.json.gz')]}.json"
        if not m.exists():
            continue
        payload = json.loads(m.read_bytes())
        if payload["data"]["attributes"].get("matchType") == "official":
            out.append((p, payload))
    return out


@pytest.fixture(scope="module")
def corpus_parse():
    corpus = _corpus()
    if not corpus:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")
    path, payload = min(corpus, key=lambda pair: pair[0].stat().st_size)
    return parse_telemetry(path.read_bytes(), match_id=payload["data"]["id"])


def test_every_roster_account_gets_a_strategy_row(corpus_parse) -> None:
    accounts = {p.account_id for p in corpus_parse.players}
    row_accounts = {r["account_id"] for r in corpus_parse.strategy_rows}
    assert row_accounts == accounts


def test_blue_dwell_is_bounded_by_the_match(corpus_parse) -> None:
    duration_s = corpus_parse.duration_ms / 1000.0
    for r in corpus_parse.strategy_rows:
        if r["blue_s"] is not None:
            assert 0.0 <= r["blue_s"] <= duration_s


def test_blue_damage_implies_blue_time(corpus_parse) -> None:
    """The dwell flag and the damage ticks are independent signals for the
    same behavior; if they disagree wholesale, one of them is misread."""
    burned = [
        r for r in corpus_parse.strategy_rows
        if r["blue_damage"] is not None and r["blue_damage"] > 50.0
    ]
    if not burned:
        pytest.skip("nobody burned in the zone in the smallest corpus match")
    with_time = [r for r in burned if r["blue_s"] and r["blue_s"] > 0.0]
    assert len(with_time) >= 0.8 * len(burned)


def test_landings_populate_and_precede_deaths(corpus_parse) -> None:
    updates = {u["account_id"]: u for u in corpus_parse.participant_updates}
    landed = [u for u in updates.values() if u["landed_at_s"] is not None]
    # A few players leave during the flight; everyone else lands exactly once.
    assert len(landed) >= 0.9 * len(updates)
    for u in landed:
        assert u["landed_at_s"] >= 0.0
        if u["died_at_s"] is not None:
            assert u["landed_at_s"] <= u["died_at_s"]


def test_first_weapon_is_found_for_nearly_everyone_who_landed(corpus_parse) -> None:
    rows = {r["account_id"]: r for r in corpus_parse.strategy_rows}
    updates = {u["account_id"]: u for u in corpus_parse.participant_updates}
    landed = [a for a, u in updates.items() if u["landed_at_s"] is not None]
    with_weapon = [a for a in landed if rows[a]["first_weapon_s"] is not None]
    assert len(with_weapon) >= 0.8 * len(landed)


def test_dwell_cap_is_wider_than_the_real_sample_cadence(corpus_parse) -> None:
    """DWELL_CAP_S was chosen from the ~10 s position cadence. Measure it:
    the *median* alive-sample gap must sit under the cap, or the clamp would
    be truncating typical gaps rather than pathological ones."""
    del corpus_parse  # the check needs raw frames, not the parse result
    corpus = _corpus()
    path, _payload = min(corpus, key=lambda pair: pair[0].stat().st_size)
    events = reader.load(path.read_bytes())
    t0_ms = next(
        reader.ts_ms(e.get("_D")) for e in events
        if reader.norm(e.get("_T", "")) == "logmatchstart"
    )
    frames = FrameIndex(t0_ms, WORLD)
    for e in events:
        frames.feed(e)
    gaps: list[float] = []
    for account in frames.accounts():
        ss = frames.samples_for(account)
        for s0, s1 in itertools.pairwise(ss):
            if s0.flags & FLAG_ALIVE:
                gaps.append((s1.t_ms - s0.t_ms) / 1000.0)
    assert gaps
    assert statistics.median(gaps) <= DWELL_CAP_S
