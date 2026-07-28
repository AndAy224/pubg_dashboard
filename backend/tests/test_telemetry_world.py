"""Zones, care packages, the plane fit, and heatmap binning.

Every case here guards a failure that renders successfully and is wrong.
"""

from __future__ import annotations

import collections
import datetime as dt
import pathlib

import pytest

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.frames import FLAG_RED_ZONE, FrameIndex
from pubg_dashboard.telemetry.heatmap import (
    ALL,
    GRID,
    KIND_MOVEMENT,
    HeatmapAccumulator,
)
from pubg_dashboard.telemetry.world import (
    WorldTracker,
    is_crate_rare,
    is_flare_vehicle,
)

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
WORLD = 816_000


def _gamestate(
    t: str, *, blue: tuple[float, float, float], white: tuple[float, float, float]
) -> dict:
    return {
        "_T": "LogGameStatePeriodic",
        "_D": t,
        "gameState": {
            # The names are inverted from their meaning — safetyZone is BLUE.
            "safetyZonePosition": {"x": blue[0], "y": blue[1], "z": 0},
            "safetyZoneRadius": blue[2],
            "poisonGasWarningPosition": {"x": white[0], "y": white[1], "z": 0},
            "poisonGasWarningRadius": white[2],
            "redZonePosition": {"x": 0, "y": 0, "z": 0},
            "redZoneRadius": 0,
            "numAlivePlayers": 50,
            "numAliveTeams": 13,
        },
    }


# ---------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------


def test_safety_zone_is_the_blue_circle_and_poison_warning_is_white() -> None:
    """The field names mean the opposite of what they say.

    Corroborated by the corpus: safetyZoneRadius is continuous (96 distinct
    values in one match) while poisonGasWarningRadius takes ~10 — the
    signature of a step function.
    """
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_gamestate("2026-07-22T00:00:00.000Z", blue=(100.0, 200.0, 300_000.0),
                      white=(400.0, 500.0, 150_000.0)))
    z = w.zones[0]
    assert (z.blue_x, z.blue_y, z.blue_r) == (100.0, 200.0, 300_000.0)
    assert (z.white_x, z.white_y, z.white_r) == (400.0, 500.0, 150_000.0)


def test_blue_interpolates_and_white_snaps() -> None:
    """Interpolating white slides the next circle across the map."""
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_gamestate("2026-07-22T00:00:00.000Z", blue=(0.0, 0.0, 1000.0),
                      white=(0.0, 0.0, 500.0)))
    w.feed(_gamestate("2026-07-22T00:00:10.000Z", blue=(100.0, 0.0, 800.0),
                      white=(900.0, 0.0, 400.0)))

    blue = w.blue_circle_at(5.0)
    assert blue is not None
    assert blue[0] == pytest.approx(50.0)  # halfway
    assert blue[2] == pytest.approx(900.0)

    white = w.white_circle_at(5.0)
    assert white is not None
    assert white[0] == pytest.approx(0.0)  # still the earlier value
    assert white[2] == pytest.approx(500.0)


def test_red_zone_track_is_emitted_but_empty() -> None:
    """redZoneRadius is 0 across all 9,771 archived game-state events.

    Ship the code path; do not ship a UI that assumes it exists.
    """
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_gamestate("2026-07-22T00:00:00.000Z", blue=(0.0, 0.0, 1.0), white=(0.0, 0.0, 1.0)))
    assert w.zones[0].red_r == 0.0


# ---------------------------------------------------------------------------
# care packages
# ---------------------------------------------------------------------------


def _package(
    t: str, kind: str, x: float, y: float, z: float, pid: str = "Carapackage_A_C"
) -> dict:
    return {
        "_T": kind,
        "_D": t,
        "itemPackage": {
            "itemPackageId": pid,
            "location": {"x": x, "y": y, "z": z},
            "items": [{"itemId": "Item_Weapon_AWM_C"}],
        },
    }


def test_care_packages_pair_on_xy_only() -> None:
    """Spawn and land share no id, and z differs by ~30 km.

    Pairing in 3D matches nothing at all, because the spawn is recorded at
    aircraft altitude.
    """
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_package(
        "2026-07-22T00:00:00.000Z", "LogCarePackageSpawn", 400_000.0, 400_000.0, 3_000_000.0
    ))
    w.feed(_package(
        "2026-07-22T00:01:00.000Z", "LogCarePackageLand", 400_100.0, 400_100.0, 1_200.0
    ))
    assert len(w.landed) == 1
    assert w.landed[0].spawn_t_s == pytest.approx(0.0)


def test_flare_vehicle_delivery_is_not_a_crate() -> None:
    """`Uaz_Armored_C` arrives through the care-package events but is a car."""
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_package(
        "2026-07-22T00:00:00.000Z", "LogCarePackageLand", 1.0, 1.0, 1.0, pid="Uaz_Armored_C"
    ))
    assert w.landed == []


def test_unpaired_landing_still_records() -> None:
    """A crate whose spawn was never seen must not be dropped."""
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    w.feed(_package("2026-07-22T00:01:00.000Z", "LogCarePackageLand", 5.0, 5.0, 5.0))
    assert len(w.landed) == 1
    assert w.landed[0].spawn_t_s is None


# ---------------------------------------------------------------------------
# plane path
# ---------------------------------------------------------------------------


def _plane_position(t: str, x: float, y: float) -> dict:
    return {
        "_T": "LogPlayerPosition",
        "_D": t,
        "character": {"accountId": "a", "location": {"x": x, "y": y, "z": 100_000}},
        # The real wire value, not 0.1.
        "common": {"isGame": 0.10000000149011612},
    }


def test_plane_fit_survives_a_north_south_flight() -> None:
    """This is why the fit is total least squares, not OLS.

    A north-south flight has every point sharing an x, so `y = mx + c` has an
    infinite slope and OLS explodes. TLS is rotation invariant.
    """
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    for i in range(10):
        w.feed(_plane_position(f"2026-07-22T00:00:{i:02d}.000Z", 400_000.0, 50_000.0 * i))
    path = w.plane_path()
    assert path is not None
    assert all(map(_finite, (path.x0, path.y0, path.x1, path.y1)))
    # A vertical line: x is constant, y spans the map.
    assert path.x0 == pytest.approx(400_000.0, abs=1.0)
    assert path.x1 == pytest.approx(400_000.0, abs=1.0)
    assert abs(path.y1 - path.y0) > 500_000.0


def test_plane_fit_direction_follows_travel() -> None:
    t0 = reader.ts("2026-07-22T00:00:00.000Z")
    w = WorldTracker(t0, WORLD)
    for i in range(10):
        w.feed(_plane_position(f"2026-07-22T00:00:{i:02d}.000Z", 50_000.0 * i, 400_000.0))
    path = w.plane_path()
    assert path is not None
    assert path.x1 > path.x0  # travelling east


def test_plane_needs_at_least_two_points() -> None:
    w = WorldTracker(0.0, WORLD)
    assert w.plane_path() is None


def _finite(v: float) -> bool:
    return v == v and abs(v) != float("inf")


# ---------------------------------------------------------------------------
# heatmap
# ---------------------------------------------------------------------------


def _acc() -> HeatmapAccumulator:
    return HeatmapAccumulator(
        map_name="Baltic_Main", game_mode="squad-fpp", day=dt.date(2026, 7, 22), world_size=WORLD
    )


def test_out_of_range_coordinates_clamp_into_the_grid() -> None:
    """A single aircraft position would otherwise index past the array."""
    h = _acc()
    h.add(KIND_MOVEMENT, -50_000.0, 9_000_000.0, "account.a")
    rows = h.rows()
    assert all(0 <= r["grid_x"] < GRID and 0 <= r["grid_y"] < GRID for r in rows)
    assert {r["grid_x"] for r in rows} == {0}
    assert {r["grid_y"] for r in rows} == {GRID - 1}


def test_one_observation_increments_all_four_filter_combinations() -> None:
    """(player, mode), (player, all), (all, mode), (all, all).

    Precomputing the cross product is what lets the API answer any combination
    of the accountId/gameMode filters from an index.
    """
    h = _acc()
    h.add(KIND_MOVEMENT, 408_000.0, 408_000.0, "account.a")
    rows = h.rows()
    assert len(rows) == 4
    assert {(r["account_id"], r["game_mode"]) for r in rows} == {
        ("account.a", "squad-fpp"),
        ("account.a", ALL),
        (ALL, "squad-fpp"),
        (ALL, ALL),
    }
    assert all(r["count"] == 1 for r in rows)


def test_repeat_observations_accumulate() -> None:
    h = _acc()
    for _ in range(3):
        h.add(KIND_MOVEMENT, 100.0, 100.0, "account.a")
    assert all(r["count"] == 3 for r in h.rows())


def test_movement_excludes_the_plane_phase() -> None:
    """Include it and every heatmap shows the flight line, not where people go.

    It still looks like a heatmap, which is what makes this expensive to catch.
    """
    h = _acc()
    h.feed(
        {
            "_T": "LogPlayerPosition",
            "_D": "2026-07-22T00:00:00.000Z",
            "character": {"accountId": "a", "location": {"x": 1000, "y": 1000, "z": 100_000}},
            "common": {"isGame": 0.10000000149011612},
        }
    )
    assert len(h) == 0

    h.feed(
        {
            "_T": "LogPlayerPosition",
            "_D": "2026-07-22T00:05:00.000Z",
            "character": {"accountId": "a", "location": {"x": 1000, "y": 1000, "z": 100}},
            "common": {"isGame": 1},
        }
    )
    assert len(h) == 4


def test_bins_never_collide_across_kinds() -> None:
    h = _acc()
    h.add("kill", 100.0, 100.0, "account.a")
    h.add("death", 100.0, 100.0, "account.a")
    assert len(h) == 8


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------


def test_corpus_zone_radii_show_the_interpolate_snap_split() -> None:
    """Blue is continuous, white is a step function — measured, not assumed."""
    root = DATA / "telemetry"
    files = sorted(root.glob("*.json.gz")) if root.is_dir() else []
    if not files:
        pytest.skip("no archived telemetry")
    biggest = max(files, key=lambda p: p.stat().st_size)
    evs = reader.load(biggest.read_bytes())
    t0 = next(
        (reader.ts(e.get("_D")) for e in evs
         if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)), 0.0
    )
    w = WorldTracker(t0, WORLD)
    for e in evs:
        w.feed(e)

    assert w.zones, "expected game-state samples"
    blue = {z.blue_r for z in w.zones}
    white = {z.white_r for z in w.zones}
    # Blue takes many more distinct values than white in every real match.
    assert len(blue) > len(white) * 3
    # Red zones are gone from the current patch.
    assert {z.red_r for z in w.zones} == {0.0}


def test_corpus_grid_indices_stay_in_range() -> None:
    root = DATA / "telemetry"
    files = sorted(root.glob("*.json.gz")) if root.is_dir() else []
    if not files:
        pytest.skip("no archived telemetry")
    evs = reader.load(files[0].read_bytes())
    h = _acc()
    for e in evs:
        h.feed(e)
    rows = h.rows()
    assert rows
    assert all(0 <= r["grid_x"] < GRID and 0 <= r["grid_y"] < GRID for r in rows)


# ---------------------------------------------------------------------------
# Red zones (parser v12)
# ---------------------------------------------------------------------------


def _corpus_telemetry(limit: int) -> list[pathlib.Path]:
    tele = DATA / "telemetry"
    if not tele.is_dir():
        return []
    return sorted(tele.glob("*.json.gz"))[:limit]


def _world_for(path: pathlib.Path) -> tuple[WorldTracker, list[dict], float]:
    events = reader.load(path.read_bytes())
    t0 = next(
        (
            reader.ts(e.get("_D"))
            for e in events
            if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)
        ),
        0.0,
    )
    w = WorldTracker(t0, WORLD)
    last = t0
    for e in events:
        w.feed(e)
        last = max(last, reader.ts(e.get("_D")))
    w.finalise_red_zones(last - t0)
    return w, events, t0


def test_corpus_red_zones_exist_and_have_a_complete_lifecycle() -> None:
    """The claim this overturns was in four documents at once.

    CLAUDE.md, BUILD-SPEC §3.9, HANDOFF §5.15 and `world.py` all said red zones
    were gone from Erangel, because `LogGameStatePeriodic.redZone*` is 0 in
    every archived match. That is true of those *fields*. The feature lives in
    `LogSpecialZoneInCharacters`.
    """
    paths = _corpus_telemetry(20)
    if not paths:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    with_zones = 0
    counts: list[int] = []
    for path in paths:
        w, _events, _t0 = _world_for(path)
        if not w.red_zones:
            continue
        with_zones += 1
        counts.append(len(w.red_zones))
        for z in w.red_zones:
            assert z.start_t_s is not None and z.end_t_s is not None, path.name
            # Monotonic, and bounded. An unclosed zone renders as a
            # bombardment that never stops, which reads as a long fight.
            assert z.warn_t_s <= z.start_t_s <= z.end_t_s, (path.name, z)
            assert 0 < z.end_t_s - z.start_t_s < 120, (path.name, z)
            # 395-500 m measured. Not asserted exactly: PUBG tunes it.
            assert 20_000 < z.radius < 90_000, (path.name, z)

    assert with_zones / len(paths) >= 0.85, f"{with_zones}/{len(paths)} matches had red zones"
    # Seven per match in every match measured. Bounded rather than pinned, so
    # a balance change is not a test failure.
    assert min(counts) >= 4 and max(counts) <= 12, counts


def test_corpus_red_zone_geometry_agrees_with_the_position_flags() -> None:
    """The check that actually proves the circles are in the right place.

    `charactersInZone` and `character.isInRedZone` come from **two independent
    event streams** — the special-zone event and the position stream — so
    agreement is real evidence rather than a restatement. If the position or
    radius were being read from the wrong field, these two would disagree and
    nothing else written here would notice: a red circle drawn in the wrong
    place still looks exactly like a red circle.
    """
    paths = _corpus_telemetry(20)
    if not paths:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    checked = 0
    for path in paths:
        w, events, t0 = _world_for(path)
        if not w.red_zones:
            continue

        # Every position sample that reported being in a red zone, by account.
        fi = FrameIndex(int(t0 * 1000), WORLD)
        for e in events:
            fi.feed(e)
        flagged: list[tuple[str, float, float, float]] = []
        for account in fi.accounts():
            for sample in fi.samples_for(account):
                if sample.flags & FLAG_RED_ZONE:
                    flagged.append((account, sample.t_ms / 1000.0 - t0, sample.x, sample.y))
        if not flagged:
            continue

        # Each flagged sample must sit inside some red zone that was *drawn*
        # around then — from the **warning**, not from the start of the
        # bombardment.
        #
        # Measured while writing this: a sample at t=633 s sits 29,157 cm from
        # a zone of radius 43,550 that was warned at 631.3 s and did not start
        # bombing until 676.3 s. So `character.isInRedZone` means "inside the
        # red circle", not "being bombed" — the flag is on for the whole 45 s
        # of warning. A test window keyed on `start_t_s` fails, and it fails
        # for a reason that says something true about the data.
        #
        # Generous on both axes: position samples are up to 10 s apart, and the
        # flag is set by the engine rather than by our arithmetic.
        for _account, t_s, x, y in flagged:
            inside = any(
                z.warn_t_s - 15 <= t_s <= (z.end_t_s or 0) + 15
                and ((x - z.x) ** 2 + (y - z.y) ** 2) ** 0.5 <= z.radius * 1.5
                for z in w.red_zones
            )
            assert inside, f"{path.name}: sample at {t_s:.0f}s ({x:.0f},{y:.0f}) in no red zone"
            checked += 1

    assert checked > 0, "no position sample was ever flagged in a red zone"


def test_flare_vehicle_deliveries_are_not_rendered_as_loot_crates() -> None:
    """The guard that matched nothing for the whole life of the feature.

    `FLARE_VEHICLE_PACKAGE` was the literal `"uaz_armored_c"`, which does not
    occur anywhere in the corpus, so 19 vehicle deliveries were classified as
    care packages. What actually arrives is `Carapackage_FlareGun_C` and
    `BP_BRDM_C` — and note PUBG spells it `Carapackage` in three package ids
    and `Carepackage` in a fourth, which is exactly why this matches on a
    lowercased substring rather than by equality.
    """
    for pid in ("Carapackage_FlareGun_C", "BP_BRDM_C", "Uaz_Armored_C", "bp_brdm_c"):
        assert is_flare_vehicle(pid), pid
    for pid in (
        "Carapackage_RedBox_C",
        "Carapackage_SmallPackage_NoParachute_C",
        "Carepackage_SmallPackage_NoParachute_Bluechip_C",
    ):
        assert not is_flare_vehicle(pid), pid

    assert is_crate_rare("Carapackage_RedBox_C")
    assert not is_crate_rare("Carepackage_SmallPackage_NoParachute_Bluechip_C")

    paths = _corpus_telemetry(20)
    if not paths:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    seen_flare = False
    for path in paths:
        w, events, _t0 = _world_for(path)
        raw = [
            str((e.get("itemPackage") or {}).get("itemPackageId") or "")
            for e in events
            if reader.norm(e.get("_T", "")) == reader.norm(E.CARE_PACKAGE_LAND)
        ]
        seen_flare |= any(is_flare_vehicle(pid) for pid in raw)
        for cp in w.landed:
            assert not is_flare_vehicle(cp.package_id), (path.name, cp.package_id)
    assert seen_flare, "no flare deliveries in the sample; the filter proves nothing"


def test_phase_changes_carry_the_white_circle_roster() -> None:
    """`playersInWhiteCircle` is ground truth for the rotation question.

    Each phase **number appears twice** per match, so anything asking "were we
    in the circle at phase N" must take the later event — the first reports
    most of the lobby.

    Note what is *not* asserted: that the roster shrinks monotonically. It does
    not. Measured on one match the sizes run 17, 15, 8, 8, 9, 5 — the circle
    keeps getting smaller but players keep rotating *into* it, so a later phase
    can hold more people than an earlier one. Only the overall direction holds.
    """
    paths = _corpus_telemetry(10)
    if not paths:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")

    saw_duplicate_phase = False
    for path in paths:
        w, _events, _t0 = _world_for(path)
        if not w.phases:
            continue
        assert any(p.in_circle for p in w.phases), path.name

        counts = collections.Counter(p.phase for p in w.phases)
        saw_duplicate_phase |= any(n > 1 for n in counts.values())

        # Last event per phase number, in phase order.
        last_per_phase: dict[int, int] = {}
        for p in w.phases:
            last_per_phase[p.phase] = len(p.in_circle)
        sizes = [last_per_phase[k] for k in sorted(last_per_phase)]
        if len(sizes) >= 3:
            assert sizes[-1] < sizes[0], (path.name, sizes)

        # Every id is a real account, never a bot: `playersInWhiteCircle` is a
        # list of account ids, and `ai.<n>` appearing here would mean it is
        # something else.
        for p in w.phases:
            for account in p.in_circle:
                assert account.startswith("account."), (path.name, account)

    assert saw_duplicate_phase, "no phase number repeated; the 'take the last' rule is untested"

