"""Map geometry: world size, asset base name, and the coordinate transform.

Telemetry coordinates are **centimetres**, origin top-left, `y` growing
*downward* — the same handedness as canvas, SVG, CSS and WebGPU screen space.
Do not flip `y`. Flipping produces a mirrored map that still looks entirely
plausible, which is why it is worth saying twice.
"""

from __future__ import annotations

from typing import Final

# Telemetry world size in centimetres, keyed by the telemetry `mapName`.
#
# Vikendi is the trap: it shipped 6x6 km and was rebuilt as 8x8 by Vikendi
# Reborn (update 21.1). Current telemetry is 816000. The old 612000/614400 only
# applies to pre-21.1 archives, which we do not have.
MAP_WORLD_SIZE: Final[dict[str, int]] = {
    "Baltic_Main": 816_000,  # Erangel (Remastered)
    "Erangel_Main": 816_000,  # legacy Erangel
    "Desert_Main": 816_000,  # Miramar
    "DihorOtok_Main": 816_000,  # Vikendi (post-Reborn)
    "Tiger_Main": 816_000,  # Taego
    "Kiki_Main": 816_000,  # Deston
    "Neon_Main": 816_000,  # Rondo
    "Savage_Main": 408_000,  # Sanhok
    "Chimera_Main": 306_000,  # Paramo
    "Summerland_Main": 204_000,  # Karakin
    "Range_Main": 204_000,  # Camp Jackal
    "Heaven_Main": 102_000,  # Haven
}

# `Assets/Maps` filenames are keyed by *display* name while `Assets/Icons/Map`
# is keyed by the `mapName` code. Two conventions in one repo, hence this table.
MAP_ASSET_BASE: Final[dict[str, str]] = {
    "Baltic_Main": "Erangel_Main",
    "Erangel_Main": "Erangel_Main",
    "Desert_Main": "Miramar_Main",
    "Savage_Main": "Sanhok_Main",
    "DihorOtok_Main": "Vikendi_Main",
    "Summerland_Main": "Karakin_Main",
    "Chimera_Main": "Paramo_Main",
    "Heaven_Main": "Haven_Main",
    "Tiger_Main": "Taego_Main",
    "Kiki_Main": "Deston_Main",
    "Neon_Main": "Rondo_Main",
    "Range_Main": "Camp_Jackal_Main",
}

MAP_DISPLAY_NAME: Final[dict[str, str]] = {
    "Baltic_Main": "Erangel",
    "Erangel_Main": "Erangel",
    "Desert_Main": "Miramar",
    "Savage_Main": "Sanhok",
    "DihorOtok_Main": "Vikendi",
    "Summerland_Main": "Karakin",
    "Chimera_Main": "Paramo",
    "Heaven_Main": "Haven",
    "Tiger_Main": "Taego",
    "Kiki_Main": "Deston",
    "Neon_Main": "Rondo",
    "Range_Main": "Camp Jackal",
}

# PUBG ships maps before anyone documents them, so an unknown mapName must not
# crash a parse. 816000 is the size of 7 of the 12 known maps and every map
# added since 2019; a wrong-but-sane default puts the dots in the right shape
# on the wrong scale, which is visibly wrong. Raising here would instead lose
# the whole match.
DEFAULT_WORLD_SIZE: Final = 816_000

# The map image is exported at 8192 px but covers only 8160 m of world on the
# 816000 maps, so pixel math needs 8160/8192. It applies to *those maps only*;
# every other map's image is an exact fit and K = 1.
#
# Single-sourced from pubg.sh. Verify it against a landmark on the first real
# render — 0.4% is 32 m at the edge of Erangel, enough to put a kill in the sea.
IMAGE_SCALE_CORRECTION: Final = 8160 / 8192  # 0.99609375


def world_size(map_name: str) -> int:
    """Telemetry world size in cm. Unknown maps fall back to 816000."""
    return MAP_WORLD_SIZE.get(map_name, DEFAULT_WORLD_SIZE)


def asset_base(map_name: str) -> str:
    """`Assets/Maps` base filename, falling back to the raw code."""
    return MAP_ASSET_BASE.get(map_name, map_name)


def display_name(map_name: str) -> str:
    return MAP_DISPLAY_NAME.get(map_name, map_name)


def image_scale(map_name: str) -> float:
    """The `K` factor for cm -> pixel conversion on this map."""
    return IMAGE_SCALE_CORRECTION if world_size(map_name) == 816_000 else 1.0


def to_pixels(cm: float, map_name: str, image_size_px: int) -> float:
    """Convert a telemetry coordinate to a pixel offset. **No y flip** — pass
    `x` and `y` through the same call."""
    size = world_size(map_name)
    return (cm / size) * image_size_px * image_scale(map_name)
