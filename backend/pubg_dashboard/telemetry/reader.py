"""Decoding the raw event stream, and the three traps in doing so.

1. **Event names must be dispatched case-insensitively.** PUBG's own docs say
   `LogItemPickupFromLootbox`; the wire says `LogItemPickupFromLootBox` (capital
   B) 26,000+ times in our corpus. Console and PC have also differed per PUBG's
   changelog. Every lookup here lowercases first.

2. **`_D` can carry 7 fractional digits.** `LogMatchDefinition` does, and
   Python's `%f` accepts at most 6 — `datetime.fromisoformat` raises on it
   before 3.11 and still rejects some shapes. The fraction is truncated to 6.

3. **File order is authoritative; the array is not sorted by `_D`.**
   `LogMatchDefinition` is element 0 with a timestamp ~84 s *later* than element
   1, and the last element is not `LogMatchEnd`. Anything that needs time order
   must sort **stably on `(_D, original_index)`**, never on `_D` alone.
"""

from __future__ import annotations

import datetime as dt
import gzip
import re
from collections.abc import Iterator, Mapping
from typing import Any, Final

import orjson

__all__ = [
    "iter_events",
    "load",
    "norm",
    "sorted_by_time",
    "ts",
    "ts_ms",
]

# Matches the fractional-seconds group of an ISO-8601 timestamp so it can be
# clipped to microsecond precision.
_FRACTION: Final = re.compile(r"\.(\d{7,})")

_GZIP_MAGIC: Final = b"\x1f\x8b"


def load(raw: bytes) -> list[dict[str, Any]]:
    """Decode a telemetry file into its event list.

    Accepts gzipped or plain bytes — the archive stores `.json.gz`, but an
    httpx client that transparently decoded `Content-Encoding: gzip` hands back
    plain JSON, and both reach this function. Sniffed on the magic number
    rather than the file extension.
    """
    if raw[:2] == _GZIP_MAGIC:
        raw = gzip.decompress(raw)
    payload = orjson.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f"telemetry must be a JSON array, got {type(payload).__name__}")
    return payload


def iter_events(raw: bytes) -> Iterator[dict[str, Any]]:
    """`load` as an iterator, for callers that do not need the list."""
    yield from load(raw)


def norm(name: str | None) -> str:
    """Canonical (lowercased) form of an event name or enum value.

    Used for every `_T` dispatch and for enum comparisons whose casing PUBG has
    changed before — `subCategory` is `"BackPack"` on the current patch and
    `"Backpack"` on 2018 data, and the official enum file still says the latter.
    """
    return name.lower() if name else ""


def ts(value: str | None) -> float:
    """ISO-8601 `_D` to epoch **seconds**. Returns 0.0 for a missing value.

    Tolerant by design: an unparseable timestamp on one event must not abort a
    37,000-event match.
    """
    if not value:
        return 0.0
    try:
        return _parse(value).timestamp()
    except ValueError:
        return 0.0


def ts_ms(value: str | None) -> int:
    """`ts` in integer milliseconds — the unit the replay bundle records."""
    return int(ts(value) * 1000.0)


def _parse(value: str) -> dt.datetime:
    # Truncate to microseconds: LogMatchDefinition._D carries 7 fractional
    # digits and Python accepts at most 6.
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6], value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    # PUBG emits Zulu throughout; a naive value means someone stripped tzinfo,
    # not that it is local time.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def sorted_by_time(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable sort on `(_D, original index)`.

    The original index is the tiebreaker on purpose: many events share a
    millisecond, and file order is the only signal for which came first. A plain
    `sort(key=_D)` is stable in Python and would do — this spells it out so the
    guarantee survives someone switching to `sorted(reverse=...)`.
    """
    return [e for _, _, e in sorted((ts(e.get("_D")), i, e) for i, e in enumerate(events))]


def field(event: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    """First present key among `names`, for fields PUBG spells two ways.

    `LogVehicleDestroy` carries `atackId` on some events and `attackId` on
    others; both spellings are real and neither is a typo we may correct.
    """
    for name in names:
        if name in event:
            return event[name]
    return default
