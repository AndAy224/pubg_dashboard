# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx", "pillow"]
# ///
"""Download PUBG's map images and cut them into a webp tile pyramid.

    uv run scripts/fetch_map_assets.py              # only maps in the archive
    uv run scripts/fetch_map_assets.py --all        # every known map
    uv run scripts/fetch_map_assets.py --map Baltic_Main --no-text

Four things about `pubg/api-assets` that will waste an afternoon otherwise:

1.  **The High_Res PNGs are Git-LFS pointers on `raw.githubusercontent.com`.**
    That URL returns 133 bytes of ASCII beginning `version https://git-lfs...`,
    with `Content-Type: image/png` and HTTP 200. Nothing about the response
    says "this is not an image" — Pillow just fails on it later. The real bytes
    are on `media.githubusercontent.com/media/...`. This script checks for the
    pointer explicitly and says so.

2.  **The file extension lies.** `Rondo_Main_Low_Res.png` is a JPEG. Format is
    taken from Pillow's sniffing, never from the name.

3.  **Not every map is 8192x8192.** `Boardwalk_No_Text_High_Res.png` is
    4096x4096. The pyramid depth is derived from the actual decoded size rather
    than assumed, and recorded in the manifest.

4.  **Two naming conventions in one repo.** `Assets/Maps` is keyed by *display*
    name (`Erangel_Main`) while telemetry uses the map *code* (`Baltic_Main`).
    `MAP_ASSET_BASE` is the translation and is not optional.

The repo has been frozen since 2024-10-28, so a map added since will 404 here.
That is reported, not raised: one missing map must not stop the others.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Final

import httpx
from PIL import Image

REPO_ROOT: Final = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR: Final = REPO_ROOT / "assets" / "maps"
CACHE_DIR: Final = REPO_ROOT / "assets" / ".source"

# The LFS media endpoint. `raw.githubusercontent.com` serves the pointer file.
MEDIA_BASE: Final = "https://media.githubusercontent.com/media/pubg/api-assets/master/Assets/Maps"

TILE_PX: Final = 512
#: First bytes of a Git-LFS pointer file.
LFS_MAGIC: Final = b"version https://git-lfs"

# Telemetry mapName -> Assets/Maps base name. Duplicated from
# telemetry/maps.py so this script stays runnable with `uv run` and no project
# install; the two must agree.
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

MAP_WORLD_SIZE: Final[dict[str, int]] = {
    "Baltic_Main": 816_000, "Erangel_Main": 816_000, "Desert_Main": 816_000,
    "DihorOtok_Main": 816_000, "Tiger_Main": 816_000, "Kiki_Main": 816_000,
    "Neon_Main": 816_000, "Savage_Main": 408_000, "Chimera_Main": 306_000,
    "Summerland_Main": 204_000, "Range_Main": 204_000, "Heaven_Main": 102_000,
}


def source_url(base: str, *, no_text: bool) -> str:
    suffix = "_No_Text_High_Res.png" if no_text else "_High_Res.png"
    return f"{MEDIA_BASE}/{base}{suffix}"


def download(url: str, dest: pathlib.Path) -> pathlib.Path:
    """Fetch once and cache. These are 50-95 MB each."""
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"    cached  {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        seen = 0
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
                seen += len(chunk)
                if total:
                    print(f"\r    downloading {seen/1e6:6.1f}/{total/1e6:.1f} MB", end="")
    print()

    head = tmp.read_bytes()[:64]
    if head.startswith(LFS_MAGIC):
        tmp.unlink()
        raise RuntimeError(
            "got a Git-LFS pointer, not an image — use media.githubusercontent.com, "
            "not raw.githubusercontent.com"
        )
    tmp.replace(dest)
    return dest


def tile_map(
    map_name: str, src: pathlib.Path, out_root: pathlib.Path, *, quality: int
) -> dict[str, object]:
    """Cut one source image into a `{z}/{x}_{y}.webp` pyramid."""
    with Image.open(src) as img:
        detected = img.format  # sniffed from content, never from the filename
        img = img.convert("RGB")
        width, height = img.size
        if width != height:
            print(f"    ! {map_name} is {width}x{height}, not square — tiling anyway")

        # Depth from the real size: 8192 -> levels 0..4, 4096 -> 0..3.
        max_zoom = 0
        while TILE_PX * (2**max_zoom) < width:
            max_zoom += 1

        out_root.mkdir(parents=True, exist_ok=True)
        written = 0
        total_bytes = 0

        for zoom in range(max_zoom, -1, -1):
            side = TILE_PX * (2**zoom)
            level = img if side == width else img.resize((side, side), Image.LANCZOS)
            n = 2**zoom
            zdir = out_root / str(zoom)
            zdir.mkdir(parents=True, exist_ok=True)
            for ty in range(n):
                for tx in range(n):
                    box = (tx * TILE_PX, ty * TILE_PX, (tx + 1) * TILE_PX, (ty + 1) * TILE_PX)
                    tile = level.crop(box)
                    path = zdir / f"{tx}_{ty}.webp"
                    tile.save(path, "WEBP", quality=quality, method=4)
                    written += 1
                    total_bytes += path.stat().st_size
                    tile.close()
            if level is not img:
                level.close()
            print(f"      z{zoom}: {n}x{n} tiles")

    return {
        "mapName": map_name,
        "assetBase": MAP_ASSET_BASE.get(map_name, map_name),
        "sourceFormat": detected,
        "sourcePx": width,
        "tilePx": TILE_PX,
        "maxZoom": max_zoom,
        "worldSize": MAP_WORLD_SIZE.get(map_name, 816_000),
        # 8160/8192 on the 816000-cm maps only; 1.0 elsewhere. Skip it and
        # every point drifts ~0.4% — 32 m at the edge of Erangel.
        "imageScale": (8160 / 8192) if MAP_WORLD_SIZE.get(map_name) == 816_000 else 1.0,
        "tiles": written,
        "bytes": total_bytes,
    }


def maps_in_archive() -> list[str]:
    """Map codes actually present in the match archive."""
    found: set[str] = set()
    match_dir = REPO_ROOT / "data" / "matches"
    for path in sorted(match_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_bytes())
            found.add(payload["data"]["attributes"]["mapName"])
        except Exception:  # noqa: BLE001 - a bad file should not stop discovery
            continue
    return sorted(found)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", action="append", dest="maps", help="Telemetry mapName. Repeatable.")
    ap.add_argument("--all", action="store_true", help="Every known map, not just played ones.")
    ap.add_argument("--no-text", action="store_true", help="Use the label-free variant.")
    ap.add_argument("--quality", type=int, default=82, help="webp quality (default 82).")
    ap.add_argument("--force", action="store_true", help="Re-tile even if output exists.")
    args = ap.parse_args()

    if args.maps:
        wanted = args.maps
    elif args.all:
        wanted = sorted(MAP_ASSET_BASE)
    else:
        wanted = maps_in_archive()
        if not wanted:
            print("no matches archived; pass --map or --all")
            return 1
        print(f"maps present in the archive: {', '.join(wanted)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "manifest.json"
    manifest: dict[str, object] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    failures: list[tuple[str, str]] = []
    for map_name in wanted:
        base = MAP_ASSET_BASE.get(map_name)
        if base is None:
            failures.append((map_name, "unknown map code — add it to MAP_ASSET_BASE"))
            continue

        out_root = OUT_DIR / map_name
        if out_root.exists() and not args.force and map_name in manifest:
            print(f"  {map_name}: already tiled (use --force to redo)")
            continue

        print(f"  {map_name} -> {base}")
        started = time.time()
        try:
            variant = "_No_Text_High_Res" if args.no_text else "_High_Res"
            src = download(
                source_url(base, no_text=args.no_text),
                CACHE_DIR / f"{base}{variant}.png",
            )
            info = tile_map(map_name, src, out_root, quality=args.quality)
        except httpx.HTTPStatusError as exc:
            # The repo froze in Oct 2024, so a newer map simply is not there.
            failures.append((map_name, f"HTTP {exc.response.status_code} — not in api-assets"))
            continue
        except Exception as exc:  # noqa: BLE001 - one bad map must not stop the rest
            failures.append((map_name, f"{type(exc).__name__}: {exc}"))
            continue

        info["noText"] = args.no_text
        manifest[map_name] = info
        print(
            f"    {info['tiles']} tiles, {info['bytes']/1e6:.1f} MB, "
            f"source {info['sourceFormat']} {info['sourcePx']}px, "
            f"maxZoom {info['maxZoom']} — {time.time()-started:.0f}s"
        )

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"\nmanifest: {manifest_path}")
    for name, why in failures:
        print(f"  ! {name}: {why}")
    return 1 if failures and not manifest else 0


if __name__ == "__main__":
    sys.exit(main())
