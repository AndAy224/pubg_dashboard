"""Zones, care packages, the plane fit, and heatmap binning.

Every case here guards a failure that renders successfully and is wrong.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.heatmap import (
    ALL,
    GRID,
    KIND_MOVEMENT,
    HeatmapAccumulator,
)
from pubg_dashboard.telemetry.world import WorldTracker

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
