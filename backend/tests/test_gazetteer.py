"""The place-name gazetteer, checked against the corpus it was built from.

The artifact is committed, so most of these run on a source-only checkout. The
two that need `data/` skip cleanly, per the repo convention.

The load-bearing test is `test_landing_events_rarely_carry_a_zone`: it pins the
*reason this whole mechanism exists*. If PUBG ever starts populating
`LogParachuteLanding.character.zone`, that test fails and tells whoever is
reading that a much simpler path has opened. A workaround nobody asserts is a
workaround that outlives its cause.
"""

from __future__ import annotations

import gzip
import json
import pathlib

import orjson
import pytest

from pubg_dashboard.config import get_settings
from pubg_dashboard.telemetry.gazetteer import (
    PLACES_DIR,
    Gazetteer,
    available_maps,
    load_gazetteer,
)

ERANGEL = "Baltic_Main"


@pytest.fixture(scope="module")
def erangel() -> Gazetteer:
    g = load_gazetteer(ERANGEL)
    if g is None:
        pytest.skip(f"no gazetteer artifact for {ERANGEL}")
    return g


def _telemetry_files() -> list[pathlib.Path]:
    root = pathlib.Path(get_settings().telemetry_dir)
    return sorted(root.glob("*.json.gz")) if root.is_dir() else []


# ---------------------------------------------------------------------------
# the artifact
# ---------------------------------------------------------------------------


def test_an_artifact_exists() -> None:
    assert available_maps(), (
        f"no gazetteer artifacts under {PLACES_DIR} — run scripts/build_gazetteer.py"
    )


def test_geometry_matches_the_heatmap_grid(erangel: Gazetteer) -> None:
    """Same grid as `heatmap_bins`, so a place cell and a heat cell are the
    same square of ground and the two can be overlaid without a transform."""
    assert erangel.grid == 256
    assert erangel.world_size == 816_000


def test_modal_purity_is_high(erangel: Gazetteer) -> None:
    """Purity is the coordinate-transform canary.

    A wrong transform still produces a plausible-looking map of names — it just
    scatters each name across cells, so every cell becomes a near-tie. Measured
    0.9847 when built; anything under 0.95 means the binning moved.
    """
    purity = erangel.built_from.get("modalPurity")
    assert purity is not None
    assert purity >= 0.95, f"modal purity {purity} — the coordinate transform is suspect"


def test_names_are_plausible_and_numerous(erangel: Gazetteer) -> None:
    assert len(erangel.names) >= 20, erangel.names
    # PUBG's spelling, lowercased at build time. Every enum here is open, so
    # this checks the shape rather than an exhaustive list.
    for name in erangel.names:
        assert name == name.lower()
        assert name.isalnum(), name


def test_the_event_marker_is_excluded(erangel: Gazetteer) -> None:
    """`8thEventSpot` is a limited-time event marker, not a place.

    It occurs 50 times in the corpus and **never alone** — always alongside
    `ferrypier`. Left in, it would name a cell after an event that has ended.
    """
    assert "8theventspot" not in erangel.names
    assert "ferrypier" in erangel.names, "the zone it co-occurs with should survive"


def test_most_of_the_map_has_no_name(erangel: Gazetteer) -> None:
    """The anti-vacuous guard, and it is the important one here.

    A bug that named every cell would make every drop cluster confidently
    "Pochinki". Measured ~9% of the grid is named, and open country having no
    name is the correct answer rather than a gap to fill.
    """
    named = len(erangel.cells)
    total = erangel.grid * erangel.grid
    assert named > 0
    assert named / total < 0.3, f"{named / total:.0%} of the grid is named — too much"


def test_a_missing_map_returns_none_not_an_empty_gazetteer() -> None:
    """None and "a map with no places" must stay distinguishable.

    An empty `Gazetteer` would label every drop `unnamed` and look like a map
    with no towns, rather than like a map nobody has built names for.
    """
    assert load_gazetteer("No_Such_Map_Main") is None


def test_the_artifact_round_trips() -> None:
    path = PLACES_DIR / f"{ERANGEL.lower()}.json"
    if not path.is_file():
        pytest.skip("no Erangel artifact")
    doc = json.loads(path.read_text())
    for cell in doc["cells"]:
        gx, gy, name_idx, support = cell
        assert 0 <= gx < doc["grid"]
        assert 0 <= gy < doc["grid"]
        assert 0 <= name_idx < len(doc["names"])
        assert support > 0


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


#: Points taken from the **map image's own printed labels**, which is the only
#: independent oracle available for this. Verified by cropping
#: `assets/.source/Erangel_Main_High_Res.png` at each coordinate and reading
#: the label PUBG printed there — the same method that settled the y-inversion
#: question. Metres.
KNOWN_PLACES = [
    ("pochinki", 3617, 4037),
    ("school", 4310, 3299),
    ("rozhok", 3987, 2918),
    ("georgopol", 1806, 2629),
    ("sosnovkamilitarybase", 4502, 6346),
    ("prison", 6245, 3753),
    ("mansion", 6208, 2991),
    ("severny", 3801, 1227),
    ("primorsk", 1642, 6112),
    ("lipovka", 7087, 3291),
]


@pytest.mark.parametrize(("expected", "x_m", "y_m"), KNOWN_PLACES)
def test_known_places_resolve_to_themselves(
    erangel: Gazetteer, expected: str, x_m: int, y_m: int
) -> None:
    """Each centroid lands on the town the map image names there.

    This is what catches a mirrored or transposed map — the failure mode that
    produces an entirely plausible gazetteer where every name is in the wrong
    place. Swapping x and y here would put Pochinki in Rozhok and nothing else
    would look wrong.
    """
    label = erangel.label(x_m * 100, y_m * 100)
    assert label.name == expected, f"({x_m}, {y_m}) resolved to {label.name}"


def test_a_transposed_lookup_would_fail(erangel: Gazetteer) -> None:
    """Prove the previous test can actually fail.

    If x/y were symmetric across the corpus the parametrised test above would
    pass under a transpose and guard nothing, so assert that at least one known
    place resolves differently with its coordinates swapped.
    """
    disagreements = sum(
        1
        for name, x_m, y_m in KNOWN_PLACES
        if erangel.label(y_m * 100, x_m * 100).name != name
    )
    assert disagreements >= len(KNOWN_PLACES) - 2


def test_open_country_has_no_name_but_still_has_a_reference(erangel: Gazetteer) -> None:
    """Unnamed is a real answer, and it still points somewhere useful.

    The UI renders this as "unnamed — 1.4 km NW of Gatka". Returning the
    nearest name as if it were the place would silently relabel a field in the
    middle of nowhere as a town.
    """
    label = erangel.label(200 * 100, 200 * 100)
    assert label.name is None
    assert label.nearest is not None
    assert label.nearest_distance_m is not None
    assert label.nearest_distance_m > 150


def test_the_within_radius_is_honoured(erangel: Gazetteer) -> None:
    far = erangel.label(200 * 100, 200 * 100, within_m=100_000)
    assert far.name is not None, "a huge radius should reach the nearest place"


def test_lookup_clamps_rather_than_raising(erangel: Gazetteer) -> None:
    """A coordinate outside the world is a rounding artefact, not a crash."""
    assert erangel.label(-500.0, -500.0) is not None
    assert erangel.label(9_000_000.0, 9_000_000.0) is not None


# ---------------------------------------------------------------------------
# the corpus fact this whole mechanism exists for
# ---------------------------------------------------------------------------


def test_landing_events_rarely_carry_a_zone() -> None:
    """**Why the gazetteer exists at all.**

    `LogParachuteLanding` is the one event that says where a player dropped,
    and it is the one event that almost never names the place — measured 1.2%.
    Every other zone-carrying event runs 30-60%.

    If this ever starts passing at a high rate, PUBG began populating the field
    and the drop report can read the name straight off the landing. That would
    be worth knowing, so it is asserted rather than left as a comment.
    """
    files = _telemetry_files()
    if not files:
        pytest.skip("no telemetry corpus")

    landings = with_zone = 0
    for path in files[:8]:
        with gzip.open(path, "rb") as fh:
            events = orjson.loads(fh.read())
        for event in events:
            if str(event.get("_T", "")).lower() != "logparachutelanding":
                continue
            landings += 1
            character = event.get("character") or {}
            if character.get("zone"):
                with_zone += 1

    if landings == 0:
        pytest.skip("no landing events in the sampled corpus")
    share = with_zone / landings
    assert share < 0.05, (
        f"LogParachuteLanding now carries a zone {share:.1%} of the time "
        f"({with_zone}/{landings}) — the gazetteer may no longer be needed"
    )


def test_zone_names_in_the_corpus_are_all_in_the_artifact(erangel: Gazetteer) -> None:
    """No Erangel zone name is missing from the built gazetteer.

    Catches a build that silently dropped a town — the cells would just be
    unnamed, which looks like open country rather than like a bug.
    """
    files = _telemetry_files()
    if not files:
        pytest.skip("no telemetry corpus")

    seen: set[str] = set()
    for path in files[:6]:
        with gzip.open(path, "rb") as fh:
            events = orjson.loads(fh.read())
        if not any(
            str(e.get("_T", "")).lower() == "logmatchstart" and e.get("mapName") == ERANGEL
            for e in events
        ):
            continue
        for event in events:
            for value in event.values():
                if isinstance(value, dict) and isinstance(value.get("zone"), list):
                    seen.update(str(z).lower() for z in value["zone"])

    if not seen:
        pytest.skip("no Erangel zone samples in the sampled corpus")
    # `8theventspot` is deliberately excluded; everything else must be present.
    missing = seen - {"8theventspot"} - set(erangel.names)
    assert not missing, f"zone names seen in telemetry but absent from the gazetteer: {missing}"
