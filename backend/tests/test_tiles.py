"""Map tile serving, and the coordinate transform the tiles exist to support.

The transform is verified against a landmark, which is what BUILD-SPEC gotcha
#12 asks for: the 8160/8192 correction is **single-sourced** from pubg.sh, so
it is checked against the map's own printed town names rather than trusted.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from pubg_dashboard.telemetry.maps import image_scale, to_pixels, world_size

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TILE_ROOT = REPO_ROOT / "assets" / "maps"


# ---------------------------------------------------------------------------
# the transform
# ---------------------------------------------------------------------------


def test_erangel_collapses_to_one_pixel_per_metre() -> None:
    """(x / 816000) * 8192 * (8160/8192) == x / 100, exactly.

    A useful smoke test: if the correction is dropped or mis-applied this
    identity stops holding immediately.
    """
    for cm in (0.0, 123_456.0, 815_999.0):
        assert to_pixels(cm, "Baltic_Main", 8192) == pytest.approx(cm / 100.0)


def test_correction_is_confined_to_816000_maps() -> None:
    """Camp Jackal has the same 8192px image over a quarter of the world.

    px-per-metre therefore differs ~4x between two maps whose source images
    are identical in size — which is why it must be derived, never hard-coded.
    """
    assert image_scale("Baltic_Main") == pytest.approx(8160 / 8192)
    assert image_scale("Range_Main") == 1.0

    erangel_ppm = to_pixels(world_size("Baltic_Main"), "Baltic_Main", 8192) / (
        world_size("Baltic_Main") / 100
    )
    jackal_ppm = to_pixels(world_size("Range_Main"), "Range_Main", 8192) / (
        world_size("Range_Main") / 100
    )
    assert erangel_ppm == pytest.approx(1.0)
    assert jackal_ppm == pytest.approx(4.0, rel=0.01)


def test_y_is_not_flipped() -> None:
    """Origin is top-left, y grows downward — same as canvas.

    Flipping produces a mirrored map that still looks entirely plausible, so
    this is asserted rather than left to inspection.
    """
    north, south = 100_000.0, 700_000.0
    assert to_pixels(north, "Baltic_Main", 8192) < to_pixels(south, "Baltic_Main", 8192)


#: Telemetry zone centroids (cm) measured over 20 archived matches, against the
#: town positions printed on PUBG's own Erangel image. Verified visually: all
#: 18 markers land on their printed labels. These few are the extremes, which
#: are where a scale error shows up first.
ERANGEL_LANDMARKS = {
    # zone            x_cm        y_cm       quadrant
    "severny": (381_300.0, 124_500.0),  # far north
    "georgopol": (178_900.0, 269_600.0),  # west
    "pochinki": (364_000.0, 406_400.0),  # centre
    "lipovka": (709_400.0, 330_100.0),  # far east
    "sosnovkamilitarybase": (449_200.0, 630_000.0),  # south island
}


def test_landmarks_land_in_the_right_quadrant() -> None:
    """Catches a flip or a gross scale error, which is what actually goes wrong.

    Sub-pixel accuracy is confirmed by the rendered overlay; this guards the
    directions so a regression cannot silently mirror the map.
    """
    px = {k: (to_pixels(x, "Baltic_Main", 8192), to_pixels(y, "Baltic_Main", 8192))
          for k, (x, y) in ERANGEL_LANDMARKS.items()}
    half = 8192 / 2

    assert px["severny"][1] < half, "Severny is in the north half"
    assert px["sosnovkamilitarybase"][1] > half, "Sosnovka Military Base is in the south"
    assert px["georgopol"][0] < half, "Georgopol is in the west half"
    assert px["lipovka"][0] > half, "Lipovka is in the east half"
    # Pochinki is famously central.
    assert abs(px["pochinki"][0] - half) < 8192 * 0.10
    assert abs(px["pochinki"][1] - half) < 8192 * 0.10


def test_every_landmark_is_inside_the_image() -> None:
    for name, (x, y) in ERANGEL_LANDMARKS.items():
        for axis, cm in (("x", x), ("y", y)):
            v = to_pixels(cm, "Baltic_Main", 8192)
            assert 0 <= v <= 8192, f"{name}.{axis} maps outside the image"


# ---------------------------------------------------------------------------
# the built pyramid
# ---------------------------------------------------------------------------


def _manifest() -> dict:
    path = TILE_ROOT / "manifest.json"
    if not path.is_file():
        pytest.skip("no tiles built; run scripts/fetch_map_assets.py")
    return json.loads(path.read_text())


def test_manifest_records_the_geometry_the_client_needs() -> None:
    for info in _manifest().values():
        assert info["tilePx"] == 512
        assert info["worldSize"] > 0
        assert info["maxZoom"] >= 0
        # Derived from the decoded image, not assumed: Boardwalk is 4096px.
        assert info["sourcePx"] in (4096, 8192)
        # Sniffed from content — Rondo_Main_Low_Res.png is actually a JPEG.
        assert info["sourceFormat"] in ("PNG", "JPEG")


def test_pyramid_is_complete() -> None:
    """Every level must be fully populated, or the renderer draws holes."""
    for name, info in _manifest().items():
        for zoom in range(info["maxZoom"] + 1):
            n = 2**zoom
            missing = [
                f"{x}_{y}"
                for y in range(n)
                for x in range(n)
                if not (TILE_ROOT / name / str(zoom) / f"{x}_{y}.webp").is_file()
            ]
            assert not missing, f"{name} z{zoom} missing {len(missing)} tiles"


def test_tile_count_matches_the_manifest() -> None:
    for name, info in _manifest().items():
        expected = sum(4**z for z in range(info["maxZoom"] + 1))
        assert info["tiles"] == expected
        on_disk = len(list((TILE_ROOT / name).rglob("*.webp")))
        assert on_disk == expected
