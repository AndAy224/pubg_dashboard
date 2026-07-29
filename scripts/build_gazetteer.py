#!/usr/bin/env python
"""Build a place-name gazetteer for each map, from PUBG's own telemetry.

**PUBG ships the place names.** Every `Character` block carries a `zone` list —
`["pochinki"]`, `["sosnovkamilitarybase"]` — populated on roughly a third of
position events and two thirds of item pickups. This repo spent a long time
believing no place-name data existed and that a drop-spot report would have to
show bare pins.

The catch, and the reason this script exists rather than a lookup at read time:
**`LogParachuteLanding` carries a zone only ~1.2% of the time.** The one event
that says where a player dropped is the one event that almost never names the
place. So the names have to be harvested from the events that *do* carry them,
binned to a grid, and used as a lookup afterwards.

Output is one JSON artifact per map under
`backend/pubg_dashboard/telemetry/places/`, **committed to git**. It has the
same standing as `docs/reference/telemetry-observed-schema.md`: derived from
the corpus, small, regenerable, and a static fact about a map that does not
change from match to match.

### Why an artifact and not a table

A `map_places` table accumulated at parse time would be a global aggregate over
matches with no ledger — precisely the failure mode `heatmap_bins` needed the
heat ledger to survive. A reparse would double every cell's support and the
modal name would still look right, so nothing would ever surface the mistake.
Building it offline, once, makes that error impossible.

Usage, from the repo root:

    uv run scripts/build_gazetteer.py                 # every map in data/
    uv run scripts/build_gazetteer.py --map Baltic_Main
    uv run scripts/build_gazetteer.py --dry-run       # report, write nothing
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import pathlib
import sys
from typing import Any, Final

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

import orjson

from pubg_dashboard.telemetry.maps import MAP_WORLD_SIZE

REPO_ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
TELEMETRY_DIR: Final = REPO_ROOT / "data" / "telemetry"
OUT_DIR: Final = REPO_ROOT / "backend" / "pubg_dashboard" / "telemetry" / "places"

#: Same 256x256 grid `heatmap_bins` uses, so a cell here and a heat cell are the
#: same square of ground. On an 816 km map that is a 31.9 m cell — smaller than
#: any named compound, which is what keeps the modal name meaningful.
GRID: Final = 256

#: Zone entries that are not places. `8thEventSpot` is an event marker: it
#: occurs 50 times in three matches and **never alone**, always alongside
#: `ferrypier`. Left in, it would name a cell after a limited-time event.
#: Matched case-insensitively, because every PUBG enum is open and casing
#: changes between patches.
NOT_PLACES: Final[frozenset[str]] = frozenset({"8theventspot"})

#: A cell needs this many observations before it gets a name. One stray sample
#: at the edge of a zone would otherwise name a whole 32 m square.
MIN_SUPPORT: Final = 5

#: ...and the winning name needs this share of its cell's votes. Below it the
#: cell straddles a boundary and honestly has no single name.
MIN_PURITY: Final = 0.6


def _iter_zone_samples(events: list[dict[str, Any]]) -> collections.Counter[tuple[int, int, str]]:
    """Count (cell_x, cell_y, name) over every block carrying a zone.

    Any block with both `zone` and `location` counts, not just `character`:
    `LogPlayerTakeDamage` names its blocks `victim`/`attacker` and carries the
    zone on both, and more samples is strictly better for a modal vote.

    A block can carry **two** zones — measured, exactly two combinations occur:
    `rozhok`+`school` and `8thEventSpot`+`ferrypier`. Both are counted toward
    their own cells and the per-cell vote resolves it, rather than this code
    inventing a specificity ranking it cannot justify.
    """
    counts: collections.Counter[tuple[int, int, str]] = collections.Counter()
    for event in events:
        for value in event.values():
            if not isinstance(value, dict):
                continue
            zones = value.get("zone")
            if not zones or not isinstance(zones, list):
                continue
            loc = value.get("location")
            if not isinstance(loc, dict):
                continue
            x, y = loc.get("x"), loc.get("y")
            if x is None or y is None:
                continue
            for name in zones:
                lowered = str(name).lower()
                if not lowered or lowered in NOT_PLACES:
                    continue
                counts[(int(x), int(y), lowered)] += 1
    return counts


def _map_name(events: list[dict[str, Any]]) -> str | None:
    """`LogMatchStart.mapName`. Dispatch is case-insensitive by convention."""
    for event in events:
        if str(event.get("_T", "")).lower() == "logmatchstart":
            name = event.get("mapName")
            return str(name) if name else None
    return None


def build(paths: list[pathlib.Path], only_map: str | None) -> dict[str, dict[str, Any]]:
    """Bin every zone sample per map and take the modal name per cell."""
    # (map, cell) -> name -> votes
    per_map: dict[str, collections.Counter[tuple[int, int, str]]] = collections.defaultdict(
        collections.Counter
    )
    matches_seen: collections.Counter[str] = collections.Counter()

    for path in paths:
        with gzip.open(path, "rb") as fh:
            events = orjson.loads(fh.read())
        map_name = _map_name(events)
        if map_name is None:
            print(f"  {path.name}: no LogMatchStart — skipped", file=sys.stderr)
            continue
        if only_map and map_name != only_map:
            continue
        world = MAP_WORLD_SIZE.get(map_name)
        if world is None:
            print(f"  {path.name}: unknown map {map_name!r} — skipped", file=sys.stderr)
            continue

        matches_seen[map_name] += 1
        for (x, y, name), n in _iter_zone_samples(events).items():
            # Clamp rather than drop: a coordinate a few centimetres outside
            # the world is a rounding artefact, not a reason to lose a sample.
            gx = min(GRID - 1, max(0, int(x * GRID / world)))
            gy = min(GRID - 1, max(0, int(y * GRID / world)))
            per_map[map_name][(gx, gy, name)] += n

    out: dict[str, dict[str, Any]] = {}
    for map_name, cell_votes in per_map.items():
        by_cell: dict[tuple[int, int], collections.Counter[str]] = collections.defaultdict(
            collections.Counter
        )
        for (gx, gy, name), n in cell_votes.items():
            by_cell[(gx, gy)][name] += n

        names: list[str] = []
        index: dict[str, int] = {}
        cells: list[list[int]] = []
        total_votes = 0
        modal_votes = 0
        dropped_thin = 0
        dropped_mixed = 0

        for (gx, gy), votes in sorted(by_cell.items()):
            support = sum(votes.values())
            total_votes += support
            name, top = votes.most_common(1)[0]
            modal_votes += top
            if support < MIN_SUPPORT:
                dropped_thin += 1
                continue
            if top / support < MIN_PURITY:
                dropped_mixed += 1
                continue
            if name not in index:
                index[name] = len(names)
                names.append(name)
            cells.append([gx, gy, index[name], support])

        out[map_name] = {
            "map": map_name,
            "grid": GRID,
            "worldSize": MAP_WORLD_SIZE[map_name],
            "names": names,
            "cells": cells,
            "builtFrom": {
                "matches": matches_seen[map_name],
                "samples": total_votes,
                # Share of votes cast for the winning name in their own cell.
                # Below ~0.95 the coordinate transform is suspect: a wrong
                # transform scatters each name across cells and every cell
                # becomes a tie.
                "modalPurity": round(modal_votes / total_votes, 4) if total_votes else 0.0,
                "cellsDroppedThin": dropped_thin,
                "cellsDroppedMixed": dropped_mixed,
            },
        }
    return out


def _render(doc: dict[str, Any]) -> str:
    """Header pretty-printed, one `[gx, gy, nameIdx, support]` per line.

    Fully indented, each of the four integers lands on its own line and the
    file is 34k lines for 5.7k cells. Fully compact, it is one 150 KB line.
    One cell per line is the readable middle, and it stays diffable — a rebuild
    that shifts one town's boundary shows as a handful of changed lines rather
    than as the whole file.
    """
    head = {k: v for k, v in sorted(doc.items()) if k != "cells"}
    body = json.dumps(head, indent=1, sort_keys=True)
    rows = ",\n  ".join(json.dumps(cell) for cell in doc["cells"])
    # Splice `cells` back in as the last key rather than letting json.dumps
    # format it.
    return f'{body[:-2]},\n "cells": [\n  {rows}\n ]\n}}\n'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", dest="only_map", help="build one map only, e.g. Baltic_Main")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    ap.add_argument(
        "--telemetry-dir", type=pathlib.Path, default=TELEMETRY_DIR, help="corpus location"
    )
    args = ap.parse_args()

    paths = sorted(args.telemetry_dir.glob("*.json.gz"))
    if not paths:
        print(f"no telemetry under {args.telemetry_dir}", file=sys.stderr)
        return 1

    print(f"reading {len(paths)} telemetry files from {args.telemetry_dir}")
    built = build(paths, args.only_map)
    if not built:
        print("no maps produced a gazetteer", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for map_name, doc in sorted(built.items()):
        meta = doc["builtFrom"]
        print(
            f"{map_name}: {len(doc['names'])} names, {len(doc['cells'])} named cells "
            f"({100 * len(doc['cells']) / (GRID * GRID):.1f}% of the grid), "
            f"purity {meta['modalPurity']}, from {meta['matches']} matches "
            f"({meta['cellsDroppedThin']} cells too thin, {meta['cellsDroppedMixed']} mixed)"
        )
        if args.dry_run:
            continue
        target = OUT_DIR / f"{map_name.lower()}.json"
        target.write_text(_render(doc))
        print(f"  -> {target.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
