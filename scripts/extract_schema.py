# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Derive the REAL telemetry + match schema from the archived corpus.

Web documentation for PUBG's telemetry is incomplete, stale, and inconsistently
cased. This script ignores all of that and reads the actual bytes: every event
type, every field path, observed types, presence rate, and low-cardinality
value sets (i.e. de-facto enums).

Presence rate is the interesting column. A field seen in 100% of a type's
events is safe to require; one seen in 4% is optional and will crash a naive
parser on the first match where it's absent.

    uv run scripts/extract_schema.py

Writes docs/reference/telemetry-observed-schema.md + data/fixtures/schema.json
"""
from __future__ import annotations

import gzip
import json
import pathlib
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parent.parent
TELE_DIR = REPO / "data" / "telemetry"
MATCH_DIR = REPO / "data" / "matches"
OUT_DOC = REPO / "docs" / "reference" / "telemetry-observed-schema.md"
OUT_JSON = REPO / "data" / "fixtures" / "schema.json"

MAX_DISTINCT = 40      # above this a field is data, not an enum
MAX_DEPTH = 6


class FieldStat:
    __slots__ = ("count", "types", "values", "overflow")

    def __init__(self) -> None:
        self.count = 0
        self.types: Counter[str] = Counter()
        self.values: Counter[str] = Counter()
        self.overflow = False

    def observe(self, value: object) -> None:
        self.count += 1
        tname = type(value).__name__
        if value is None:
            tname = "null"
        self.types[tname] += 1
        # Only strings/bools/small ints are enum candidates.
        if isinstance(value, (str, bool)) or (isinstance(value, int) and not isinstance(value, bool)):
            if not self.overflow:
                key = repr(value)
                if len(key) <= 60:
                    self.values[key] += 1
                    if len(self.values) > MAX_DISTINCT:
                        self.overflow = True
                        self.values.clear()


def walk(obj: object, prefix: str, out: dict[str, FieldStat], depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            out.setdefault(path, FieldStat()).observe(v)
            if isinstance(v, (dict, list)):
                walk(v, path, out, depth + 1)
    elif isinstance(obj, list):
        # Collapse array indices to [] so we learn element shape, not position.
        path = f"{prefix}[]"
        for item in obj[:8]:
            if isinstance(item, (dict, list)):
                walk(item, path, out, depth + 1)
            else:
                out.setdefault(path, FieldStat()).observe(item)


def main() -> None:
    files = sorted(TELE_DIR.glob("*.json.gz"))
    if not files:
        raise SystemExit(f"No telemetry in {TELE_DIR} — run scripts/panic_archive.py first")

    event_counts: Counter[str] = Counter()
    schema: dict[str, dict[str, FieldStat]] = defaultdict(dict)
    events_per_match: dict[str, int] = {}
    matches_with_type: Counter[str] = Counter()

    print(f"Reading {len(files)} telemetry files...")
    for n, f in enumerate(files, 1):
        try:
            events = json.loads(gzip.decompress(f.read_bytes()))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {f.name}: {exc}")
            continue
        events_per_match[f.name] = len(events)
        seen_types = set()
        for e in events:
            t = e.get("_T", "UNKNOWN")
            event_counts[t] += 1
            seen_types.add(t)
            walk(e, "", schema[t])
        for t in seen_types:
            matches_with_type[t] += 1
        if n % 10 == 0 or n == len(files):
            print(f"  {n}/{len(files)} — {sum(event_counts.values()):,} events")

    # ---- match-level enums -------------------------------------------------
    match_attrs: dict[str, Counter[str]] = defaultdict(Counter)
    participant_fields: Counter[str] = Counter()
    roster_fields: dict[str, Counter[str]] = defaultdict(Counter)
    death_types: Counter[str] = Counter()
    n_matches = 0
    for f in sorted(MATCH_DIR.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n_matches += 1
        for k, v in m["data"]["attributes"].items():
            if isinstance(v, (str, bool, int)) and v is not None:
                match_attrs[k][repr(v)] += 1
        for inc in m.get("included", []):
            if inc["type"] == "participant":
                st = inc["attributes"]["stats"]
                for k in st:
                    participant_fields[k] += 1
                death_types[repr(st.get("deathType"))] += 1
            elif inc["type"] == "roster":
                a = inc["attributes"]
                roster_fields["won"][f"{v!r}" if False else repr(a.get("won"))] += 1
                roster_fields["_won_pytype"][type(a.get("won")).__name__] += 1

    total_events = sum(event_counts.values())

    # ---- write JSON --------------------------------------------------------
    out = {
        "corpus": {
            "matches": len(files),
            "matchJsonFiles": n_matches,
            "totalEvents": total_events,
            "avgEventsPerMatch": round(total_events / max(len(files), 1)),
        },
        "eventCounts": dict(event_counts.most_common()),
        "matchesContainingEvent": dict(matches_with_type),
        "matchAttributes": {k: dict(v.most_common(MAX_DISTINCT)) for k, v in match_attrs.items()},
        "participantStatFields": dict(participant_fields.most_common()),
        "deathTypes": dict(death_types),
        "rosterWon": {k: dict(v) for k, v in roster_fields.items()},
        "events": {
            t: {
                path: {
                    "presence": round(fs.count / event_counts[t], 4),
                    "types": dict(fs.types),
                    "values": dict(fs.values.most_common(MAX_DISTINCT)) if not fs.overflow else "<high-cardinality>",
                }
                for path, fs in sorted(fields.items())
            }
            for t, fields in schema.items()
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=1), encoding="utf-8")

    # ---- write markdown ----------------------------------------------------
    L: list[str] = []
    L.append("# Observed Telemetry Schema (derived from real matches)\n")
    L.append(
        "> **This document outranks every other reference and outranks PUBG's own docs.**\n"
        "> It is machine-generated by `scripts/extract_schema.py` from an archived corpus of\n"
        f"> **{len(files)} real matches / {total_events:,} events** on the current patch.\n"
        "> If a hand-written doc disagrees with this file, this file is right.\n"
    )
    L.append(f"\nRegenerate after archiving new matches:\n\n```bash\nuv run scripts/extract_schema.py\n```\n")

    L.append("\n## Corpus\n")
    L.append("| Metric | Value |\n|---|---|")
    L.append(f"| Matches | {len(files)} |")
    L.append(f"| Total events | {total_events:,} |")
    L.append(f"| Avg events/match | {round(total_events/max(len(files),1)):,} |")
    L.append(f"| Distinct event types | {len(event_counts)} |")

    L.append("\n## Match attributes (observed enum values)\n")
    for k in ("mapName", "gameMode", "matchType", "isCustomMatch", "seasonState", "shardId", "titleId"):
        if k in match_attrs:
            vals = ", ".join(f"`{v}` ×{c}" for v, c in match_attrs[k].most_common(MAX_DISTINCT))
            L.append(f"- **{k}**: {vals}")

    L.append("\n## Participant stat fields\n")
    L.append(
        f"Exactly **{len(participant_fields)}** fields are returned by the current API. "
        "Fields widely documented online but **absent here** must not be given columns.\n"
    )
    L.append("| Field | Occurrences |\n|---|---|")
    for k, c in participant_fields.most_common():
        L.append(f"| `{k}` | {c:,} |")

    L.append("\n### deathType values\n")
    L.append(", ".join(f"`{v}` ×{c:,}" for v, c in death_types.most_common()))

    L.append("\n### roster.won\n")
    pyt = ", ".join(f"`{k}`" for k in roster_fields.get("_won_pytype", {}))
    vals = ", ".join(f"`{v}` ×{c}" for v, c in roster_fields.get("won", Counter()).most_common())
    L.append(
        f"Python type: {pyt} — values: {vals}.\n\n"
        "> ⚠️ It is a **string**, not a boolean. `bool(\"false\") is True`. "
        "Parse with `== \"true\"`, never a truthiness check.\n"
    )

    L.append("\n## Event types\n")
    L.append("| Event | Count | % of events | Matches containing |\n|---|---:|---:|---:|")
    for t, c in event_counts.most_common():
        pct = 100 * c / total_events
        L.append(f"| `{t}` | {c:,} | {pct:.2f}% | {matches_with_type[t]}/{len(files)} |")

    L.append("\n## Field reference per event type\n")
    L.append(
        "`presence` = fraction of that event type's occurrences containing the field.\n"
        "**Anything below 1.00 is optional and must be accessed defensively.**\n"
    )
    for t, _ in event_counts.most_common():
        fields = schema[t]
        L.append(f"\n### `{t}`\n")
        L.append(f"Occurrences: {event_counts[t]:,} across {matches_with_type[t]} matches\n")
        L.append("| Field | Presence | Type(s) | Observed values |\n|---|---:|---|---|")
        for path, fs in sorted(fields.items()):
            presence = fs.count / event_counts[t]
            types = "/".join(f"`{k}`" for k in fs.types)
            if fs.overflow:
                vals = "*(high cardinality)*"
            elif fs.values:
                shown = [v for v, _ in fs.values.most_common(12)]
                vals = ", ".join(f"`{v}`" for v in shown)
                if len(fs.values) > 12:
                    vals += f", … (+{len(fs.values)-12})"
            else:
                vals = ""
            flag = "" if presence >= 0.999 else " ⚠️"
            L.append(f"| `{path}`{flag} | {presence:.2f} | {types} | {vals} |")

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(L) + "\n", encoding="utf-8")

    print(f"\nWrote {OUT_DOC.relative_to(REPO)}")
    print(f"Wrote {OUT_JSON.relative_to(REPO)}")
    print(f"\n{len(event_counts)} event types, {total_events:,} events, {len(files)} matches")


if __name__ == "__main__":
    main()
