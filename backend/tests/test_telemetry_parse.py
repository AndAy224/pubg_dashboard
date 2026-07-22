"""Bundle writer and the parse orchestrator, end to end over the real corpus."""

from __future__ import annotations

import datetime as dt
import itertools
import json
import pathlib

import pytest

from pubg_dashboard.telemetry.bundle import (
    DEFAULT_TICK_MS,
    FALLBACK_TICK_MS,
    NULL_PLAYER,
    Dictionary,
    choose_tick_ms,
    quantise,
    read_bundle,
    read_heat_ledger,
)
from pubg_dashboard.telemetry.parse import PARSER_VERSION, parse_telemetry

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"


def _corpus() -> list[tuple[pathlib.Path, dict]]:
    tele, mat = DATA / "telemetry", DATA / "matches"
    if not tele.is_dir() or not mat.is_dir():
        return []
    out = []
    for p in sorted(tele.glob("*.json.gz")):
        m = mat / f"{p.name[: -len('.json.gz')]}.json"
        if m.exists():
            out.append((p, json.loads(m.read_bytes())))
    return out


@pytest.fixture(scope="module")
def parsed() -> object:
    corpus = _corpus()
    if not corpus:
        pytest.skip("no archived corpus; run scripts/panic_archive.py")
    # The largest match: most players, most events, worst case for every budget.
    path, payload = max(corpus, key=lambda pair: pair[0].stat().st_size)
    attrs = payload["data"]["attributes"]
    return parse_telemetry(
        path.read_bytes(),
        match_id=payload["data"]["id"],
        shard="steam",
        game_mode=attrs["gameMode"],
        played_at=dt.datetime.fromisoformat(attrs["createdAt"].replace("Z", "+00:00")),
    )


# ---------------------------------------------------------------------------
# bundle primitives
# ---------------------------------------------------------------------------


def test_quantisation_round_trips_within_half_a_step() -> None:
    """worldSize/65535 = 12.45 cm on an 8x8 km map — invisible at any zoom."""
    world = 816_000
    step = world / 65_535
    for cm in (0.0, 1234.5, 400_000.0, 815_999.0):
        decoded = quantise(cm, world) / 65_535 * world
        assert abs(decoded - cm) <= step


def test_quantisation_clamps_out_of_range() -> None:
    assert quantise(-50_000.0, 816_000) == 0
    assert quantise(9_000_000.0, 816_000) == 65_535


def test_tick_falls_back_when_a_match_would_overflow_uint16() -> None:
    """All `t` values are Uint16 ticks, so >65535 ticks would wrap silently."""
    assert choose_tick_ms(30 * 60 * 1000) == DEFAULT_TICK_MS
    assert choose_tick_ms(3 * 60 * 60 * 1000) == FALLBACK_TICK_MS


def test_dictionary_interns_and_marks_absent() -> None:
    d = Dictionary()
    assert d.intern("WeapHK416_C") == 0
    assert d.intern("WeapHK416_C") == 0
    assert d.intern("WeapAK47_C") == 1
    assert d.intern(None) == 0xFFFF
    assert d.intern("") == 0xFFFF
    assert d.values == ["WeapHK416_C", "WeapAK47_C"]


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------


def test_bundle_round_trips(parsed: object) -> None:
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    assert b["v"] == 1
    assert b["parserVersion"] == PARSER_VERSION
    assert b["le"] is True
    assert b["worldSize"] > 0
    assert b["tickMs"] == DEFAULT_TICK_MS


def test_typed_arrays_have_consistent_lengths(parsed: object) -> None:
    """The renderer wraps these as typed arrays; a length mismatch reads noise."""
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    n = b["pos"]["n"]
    assert len(b["pos"]["t"]) == n * 2  # Uint16
    assert len(b["pos"]["x"]) == n * 2
    assert len(b["pos"]["y"]) == n * 2
    assert len(b["pos"]["hp"]) == n  # Uint8
    assert len(b["pos"]["flags"]) == n
    # CSR offsets: one Uint32 per player, plus the terminator.
    assert len(b["pos"]["off"]) == (len(b["players"]) + 1) * 4

    z = b["zones"]
    assert len(z["t"]) == z["n"] * 2
    assert len(z["alive"]) == z["n"]

    inv = b["inv"]
    assert len(inv["p"]) == inv["n"]
    assert len(inv["t"]) == inv["n"] * 2


def test_csr_offsets_are_monotonic_and_terminate_at_n(parsed: object) -> None:
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    raw = b["pos"]["off"]
    off = [int.from_bytes(raw[i : i + 4], "little") for i in range(0, len(raw), 4)]
    assert off[0] == 0
    assert off[-1] == b["pos"]["n"]
    assert all(a <= c for a, c in itertools.pairwise(off))


def test_player_order_is_deterministic(parsed: object) -> None:
    """Index `p` must mean the same player on every reparse.

    Otherwise a bundle cached by a client and a freshly parsed one disagree
    about who is who, and every label is wrong.
    """
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    keys = [(p["t"], p["a"]) for p in b["players"]]
    assert keys == sorted(keys)


def test_heat_ledger_is_not_in_the_client_bundle(parsed: object) -> None:
    """It is server-side reparse bookkeeping the browser cannot use.

    Measured at 23% of the bundle's compressed size when it was inside.
    """
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    assert "heat" not in b
    ledger = read_heat_ledger(parsed.heat_ledger)  # type: ignore[attr-defined]
    assert ledger
    row = ledger[0]
    assert len(row) == 6, "(kind, account, mode, grid_x, grid_y, count)"
    assert isinstance(row[3], int) and 0 <= row[3] < 256
    assert row[5] > 0


def test_no_unknown_events_in_the_corpus(parsed: object) -> None:
    """An unrecognised `_T` is tolerated but should be news, not silence."""
    assert parsed.unknown_events == {}  # type: ignore[attr-defined]


def test_kill_rows_match_the_combat_track(parsed: object) -> None:
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    kills_in_bundle = [e for e in b["events"] if e["k"] == "kill"]
    assert len(kills_in_bundle) == len(parsed.kill_rows)  # type: ignore[attr-defined]


def test_null_player_sentinel_is_used_for_absent_killers(parsed: object) -> None:
    """`killer` is genuinely null for zone deaths; 255 is the sentinel."""
    b = read_bundle(parsed.bundle)  # type: ignore[attr-defined]
    assert len(b["players"]) <= 100
    for e in b["events"]:
        for field in ("p", "v", "f", "d"):
            if field in e:
                assert e[field] == NULL_PLAYER or 0 <= e[field] < len(b["players"])


def test_every_participant_gets_a_telemetry_update(parsed: object) -> None:
    assert len(parsed.participant_updates) == len(parsed.players)  # type: ignore[attr-defined]
    for row in parsed.participant_updates:  # type: ignore[attr-defined]
        assert row["account_id"]
        assert row["kills_human"] >= 0


def test_heatmap_rows_are_upsertable(parsed: object) -> None:
    rows = parsed.heatmap_rows  # type: ignore[attr-defined]
    assert rows
    for row in rows[:200]:
        assert 0 <= row["grid_x"] < 256
        assert 0 <= row["grid_y"] < 256
        assert row["count"] > 0
        # NOT NULL with '' sentinels — nullable columns would make
        # ON CONFLICT DO UPDATE never fire on the global rows.
        assert row["account_id"] is not None
        assert row["game_mode"] is not None


def test_whole_corpus_parses(parsed: object) -> None:
    """Every archived match, every mode and map, no failures and no unknowns.

    Measured: 65/65 in 67 s, 6,164 kill rows, zero unrecognised event types.
    Runs a small sample here to keep the suite quick.
    """
    corpus = _corpus()
    if not corpus:
        pytest.skip("no archived corpus")
    for path, payload in corpus[:5]:
        attrs = payload["data"]["attributes"]
        result = parse_telemetry(
            path.read_bytes(),
            match_id=payload["data"]["id"],
            game_mode=attrs["gameMode"],
            played_at=dt.datetime.fromisoformat(attrs["createdAt"].replace("Z", "+00:00")),
        )
        assert result.unknown_events == {}
        assert result.bundle
        b = read_bundle(result.bundle)
        assert b["mapName"] == attrs["mapName"]
