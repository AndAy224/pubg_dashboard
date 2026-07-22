"""Foundation of the telemetry parser, checked against the real corpus.

Each test below corresponds to a trap that produces a *plausible* wrong result
rather than an error. None of them fail loudly in production, which is why they
are pinned here against real archived matches instead of hand-written samples.
"""

from __future__ import annotations

import datetime as dt
import gzip
import pathlib
from typing import Any

import orjson
import pytest

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.maps import (
    DEFAULT_WORLD_SIZE,
    IMAGE_SCALE_CORRECTION,
    image_scale,
    to_pixels,
    world_size,
)

# ---------------------------------------------------------------------------
# reader: decoding
# ---------------------------------------------------------------------------


def test_load_accepts_gzip_and_plain() -> None:
    """The archive stores .gz, but an httpx client that transparently decoded
    Content-Encoding hands back plain JSON. Both reach `load`."""
    payload = [{"_T": "LogMatchStart", "_D": "2026-07-22T15:00:00.000Z"}]
    raw = orjson.dumps(payload)
    assert reader.load(raw) == payload
    assert reader.load(gzip.compress(raw)) == payload


def test_load_rejects_a_non_array() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        reader.load(orjson.dumps({"_T": "nope"}))


# ---------------------------------------------------------------------------
# reader: the 7-fractional-digit timestamp
# ---------------------------------------------------------------------------


def test_ts_parses_seven_fractional_digits() -> None:
    """`LogMatchDefinition._D` carries 7, and Python accepts at most 6.

    60 events in the archived corpus have this shape. An unhandled one raises
    ValueError and takes the whole match with it.
    """
    assert reader.ts("2026-07-22T15:00:00.1234567Z") > 0


def test_ts_seven_digits_truncates_rather_than_rounds() -> None:
    assert reader.ts("2026-07-22T15:00:00.1234567Z") == pytest.approx(
        reader.ts("2026-07-22T15:00:00.123456Z")
    )


def test_ts_is_utc_not_local() -> None:
    expected = dt.datetime(2026, 7, 22, 15, 0, 0, tzinfo=dt.UTC).timestamp()
    assert reader.ts("2026-07-22T15:00:00.000Z") == expected
    # A naive timestamp means someone stripped tzinfo, not that it is local.
    assert reader.ts("2026-07-22T15:00:00.000") == expected


def test_ts_tolerates_garbage() -> None:
    """One unparseable timestamp must not abort a 37,000-event match."""
    assert reader.ts(None) == 0.0
    assert reader.ts("") == 0.0
    assert reader.ts("not a timestamp") == 0.0


# ---------------------------------------------------------------------------
# reader: casing
# ---------------------------------------------------------------------------


def test_norm_is_case_insensitive() -> None:
    """PUBG's docs say `LogItemPickupFromLootbox`; the wire says `...LootBox`."""
    assert reader.norm("LogItemPickupFromLootBox") == reader.norm("LogItemPickupFromLootbox")


def test_lootbox_constant_matches_the_wire_spelling() -> None:
    assert E.ITEM_PICKUP_FROM_LOOTBOX == "LogItemPickupFromLootBox"


# ---------------------------------------------------------------------------
# events: the plane phase
# ---------------------------------------------------------------------------


def test_is_game_exact_comparison_would_never_match() -> None:
    """The wire value is a 32-bit float widened, so `== 0.1` is always False.

    This single comparison gates plane-phase detection and the movement
    heatmap's flight-path filter. Getting it wrong yields a heatmap of the
    flight line instead of where people go — which still looks like a heatmap.
    """
    wire = 0.10000000149011612
    assert wire != 0.1
    assert E.is_plane_phase(wire)
    assert not E.is_in_play(wire)


def test_is_in_play_excludes_the_plane() -> None:
    assert E.is_in_play(1)
    assert E.is_in_play(3.0)
    assert not E.is_in_play(0)
    assert not E.is_in_play(None)


# ---------------------------------------------------------------------------
# events: shapes that are sentinels rather than null
# ---------------------------------------------------------------------------


def test_vehicle_sentinel_is_not_null() -> None:
    """`victimVehicle`/`killerVehicle` are zeroed objects when on foot.

    Testing `is not None` marks every on-foot kill as a vehicle kill.
    """
    on_foot = {"vehicleType": "", "vehicleId": "", "healthPercent": 0}
    assert on_foot is not None
    assert not E.has_vehicle(on_foot)
    assert E.has_vehicle({"vehicleType": "WheeledVehicle", "vehicleId": "Dacia_A_01_v2_C"})


def test_unwrap_character_handles_both_shapes() -> None:
    """`LogMatchEnd.characters[]` nests one level deeper on modern telemetry."""
    inner = {"accountId": "account.x", "ranking": 3}
    assert E.unwrap_character({"character": inner}) == inner
    assert E.unwrap_character(inner) == inner
    assert E.unwrap_character(None) is None


def test_is_bot_prefers_telemetry_over_the_id_prefix() -> None:
    # The authoritative signal, and it catches a bot given a real-looking id.
    assert E.is_bot({"type": "user_ai", "accountId": "account.deadbeef"})
    # Fallback when no character type is present.
    assert E.is_bot({"accountId": "ai.322"})
    assert not E.is_bot({"type": "user", "accountId": "account.deadbeef"})
    assert not E.is_bot(None)


# ---------------------------------------------------------------------------
# maps
# ---------------------------------------------------------------------------


def test_world_sizes() -> None:
    assert world_size("Baltic_Main") == 816_000
    assert world_size("Range_Main") == 204_000
    # Vikendi Reborn is 8x8, not the pre-21.1 6x6.
    assert world_size("DihorOtok_Main") == 816_000


def test_unknown_map_falls_back_instead_of_raising() -> None:
    """PUBG ships maps before anyone documents them; losing the match is worse."""
    assert world_size("Brand_New_Main") == DEFAULT_WORLD_SIZE


def test_image_correction_applies_only_to_816000_maps() -> None:
    assert image_scale("Baltic_Main") == IMAGE_SCALE_CORRECTION
    assert image_scale("Range_Main") == 1.0


def test_the_convenient_identity_holds() -> None:
    """On an 816000 map against the 8192 px image, cm -> px collapses to cm/100."""
    for cm in (0.0, 123_456.0, 816_000.0):
        assert to_pixels(cm, "Baltic_Main", 8192) == pytest.approx(cm / 100.0)


# ---------------------------------------------------------------------------
# Corpus checks — skipped without data/, same convention as conftest
# ---------------------------------------------------------------------------


def _telemetry_files() -> list[pathlib.Path]:
    root = pathlib.Path(__file__).resolve().parents[2] / "data" / "telemetry"
    return sorted(root.glob("*.json.gz")) if root.is_dir() else []


@pytest.fixture(scope="module")
def one_match() -> list[dict[str, Any]]:
    files = _telemetry_files()
    if not files:
        pytest.skip("no archived telemetry; run scripts/panic_archive.py")
    return reader.load(min(files, key=lambda p: p.stat().st_size).read_bytes())


def test_corpus_event_vocabulary_is_complete(one_match: list[dict[str, Any]]) -> None:
    """An unknown `_T` is not an error, but it should be news.

    All 47 types across the corpus are accounted for; if this fails, PUBG added
    an event and the parser should be taught about it rather than silently
    ignoring it.
    """
    unknown = {e.get("_T") for e in one_match if reader.norm(e.get("_T", "")) not in E.KNOWN_EVENTS}
    assert not unknown, f"unrecognised event types: {unknown}"


def test_corpus_file_order_is_not_timestamp_order(one_match: list[dict[str, Any]]) -> None:
    """True of 65/65 archived matches.

    `LogMatchDefinition` is element 0 with a `_D` ~84 s later than element 1.
    Anything needing time order must sort stably on `(_D, index)`.
    """
    stamps = [reader.ts(e.get("_D")) for e in one_match]
    assert stamps != sorted(stamps), "expected the raw array to be out of order"


def test_corpus_sorted_by_time_is_stable_and_complete(one_match: list[dict[str, Any]]) -> None:
    ordered = reader.sorted_by_time(one_match)
    assert len(ordered) == len(one_match)
    stamps = [reader.ts(e.get("_D")) for e in ordered]
    assert stamps == sorted(stamps)


def test_corpus_plane_phase_needs_a_tolerance(one_match: list[dict[str, Any]]) -> None:
    """The headline result: exact equality finds nothing, tolerance finds the plane."""
    positions = [
        (e.get("common") or {}).get("isGame")
        for e in one_match
        if reader.norm(e.get("_T", "")) == reader.norm(E.PLAYER_POSITION)
    ]
    assert sum(1 for v in positions if v == 0.1) == 0
    assert sum(1 for v in positions if E.is_plane_phase(v)) > 0
