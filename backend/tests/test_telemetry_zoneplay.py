"""Circle discipline, checked against the corpus.

The headline test is `test_roster_agrees_with_the_geometry`. `in_circle_at_close`
and `dist_to_white_edge_cm` come from **two independent event streams** —
`LogPhaseChange.playersInWhiteCircle` and `LogPlayerPosition` — so their
agreeing is real evidence that the coordinate transform is right. A wrong
transform still draws a perfectly plausible circle, and nothing else here would
catch it.

It also asserts the *shape* of the residual: disagreements must sit at higher
sample lag than agreements. That is what distinguishes "the position track is
10 s stale" from "the circle is in the wrong place". It caught exactly that —
an early version read the white circle at the announce instant, `white_circle_at`
snapped to the previous phase's circle, agreement fell to 52%, and the
disagreements had *lower* lag than the agreements. Staleness cannot produce
that pattern.
"""

from __future__ import annotations

import collections
import pathlib
import statistics
from typing import Any

import pytest

from pubg_dashboard.config import get_settings
from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.parse import parse_telemetry

#: Enough matches to be evidence, few enough to keep the suite quick.
SAMPLE = 5


def _corpus() -> list[pathlib.Path]:
    root = pathlib.Path(get_settings().telemetry_dir)
    return sorted(root.glob("*.json.gz"))[:SAMPLE] if root.is_dir() else []


@pytest.fixture(scope="module")
def parsed() -> list[Any]:
    files = _corpus()
    if not files:
        pytest.skip("no telemetry corpus")
    return [parse_telemetry(p.read_bytes(), match_id=p.name[:36]) for p in files]


@pytest.fixture(scope="module")
def rows(parsed: list[Any]) -> list[dict[str, Any]]:
    out = [r for p in parsed for r in p.zone_play_rows]
    if not out:
        pytest.skip("no zone play rows in the sampled corpus")
    return out


# ---------------------------------------------------------------------------
# the phase pair
# ---------------------------------------------------------------------------


def test_phase_kind_classifies_both_halves(parsed: list[Any]) -> None:
    """Both kinds occur. The anti-vacuous guard.

    `phase_kind` falls back to `close` on an unexpected value, so a change to
    `common.isGame` would file *everything* as a close and every "were we
    already there when it appeared" answer would silently become the deadline
    answer instead. Nothing downstream would look wrong.
    """
    kinds = collections.Counter(
        change.kind for p in parsed for change in _phases(p)
    )
    assert kinds[E.PHASE_ANNOUNCE] > 0, "no announcements classified"
    assert kinds[E.PHASE_CLOSE] > 0, "no closes classified"
    # Announcements slightly outnumber closes: a match can end on one.
    assert kinds[E.PHASE_ANNOUNCE] >= kinds[E.PHASE_CLOSE]


def test_the_announcement_is_always_the_earlier_event(parsed: list[Any]) -> None:
    """Measured 178 of 178 complete pairs, no exceptions."""
    for result in parsed:
        by_phase: dict[int, dict[str, float]] = collections.defaultdict(dict)
        for change in _phases(result):
            by_phase[change.phase][change.kind] = change.t_s
        for phase, kinds in by_phase.items():
            if len(kinds) == 2:
                assert kinds[E.PHASE_ANNOUNCE] < kinds[E.PHASE_CLOSE], (
                    f"{result.match_id} phase {phase}"
                )


def test_phase_one_is_announced_during_the_plane_phase(parsed: list[Any]) -> None:
    """Phase 1's announcement carries `isGame == 0.1`, not `0.5`.

    This is why it must be tolerance-compared: the wire value is
    `0.10000000149011612`, so `== 0.1` never matches and every phase 1 would
    be misfiled as a close.
    """
    assert E.phase_kind(1, 0.10000000149011612) == E.PHASE_ANNOUNCE
    # And the exact-comparison trap, stated as a test rather than a comment.
    assert 0.10000000149011612 != 0.1


def test_phase_kind_defaults_conservatively() -> None:
    assert E.phase_kind(3, None) == E.PHASE_CLOSE
    assert E.phase_kind(3, 3.0) == E.PHASE_CLOSE
    assert E.phase_kind(3, 2.5) == E.PHASE_ANNOUNCE
    # A value from nowhere must not raise.
    assert E.phase_kind(3, 99.0) == E.PHASE_CLOSE


# ---------------------------------------------------------------------------
# the cross-check
# ---------------------------------------------------------------------------


def test_roster_agrees_with_the_geometry(rows: list[dict[str, Any]]) -> None:
    """PUBG's roster and our own position maths must reach the same answer.

    Measured 96.7% over five matches. The threshold is deliberately well below
    that: the remaining few percent are genuine 10-second-stale position
    samples, and tightening this to 99% would make it fail on a quiet track
    rather than on a real defect.
    """
    both = [
        (r["in_circle_at_close"], r["dist_to_white_edge_cm"])
        for r in rows
        if r["in_circle_at_close"] is not None and r["dist_to_white_edge_cm"] is not None
    ]
    assert len(both) > 100, "too few comparable rows to be evidence"
    agree = sum(1 for named, edge in both if named == (edge <= 0))
    share = agree / len(both)
    assert share > 0.90, f"roster and geometry agree on only {share:.1%} of rows"


def test_disagreements_are_explained_by_stale_positions(
    rows: list[dict[str, Any]],
) -> None:
    """The shape of the residual, which is the part that catches a bad transform.

    If the circle were in the wrong place the disagreements would be spread
    across all sample lags, or concentrated at *low* lag. Requiring them to sit
    at higher lag than the agreements is what separates "our position is a few
    seconds old" from "our circle is wrong".
    """
    comparable = [
        (r["in_circle_at_close"], r["dist_to_white_edge_cm"], r["sample_lag_ms"])
        for r in rows
        if r["in_circle_at_close"] is not None
        and r["dist_to_white_edge_cm"] is not None
        and r["sample_lag_ms"] is not None
    ]
    agree = [lag for named, edge, lag in comparable if named == (edge <= 0)]
    disagree = [lag for named, edge, lag in comparable if named != (edge <= 0)]
    if len(disagree) < 5:
        pytest.skip("too few disagreements to characterise")
    assert statistics.median(disagree) > statistics.median(agree), (
        "disagreements are not concentrated at stale samples — suspect the "
        "circle, not the position cadence"
    )


# ---------------------------------------------------------------------------
# row shape
# ---------------------------------------------------------------------------


def test_every_in_circle_state_occurs(rows: list[dict[str, Any]]) -> None:
    """All four combinations of (announce, close) appear.

    An early version emitted rows only for players named in a roster, so
    `(False, False)` — outside at both instants, the most common state for a
    losing squad — never appeared at all. The page would have shown perfect
    circle discipline.
    """
    seen = {
        (r["in_circle_at_announce"], r["in_circle_at_close"])
        for r in rows
        if r["in_circle_at_announce"] is not None and r["in_circle_at_close"] is not None
    }
    for combination in ((True, True), (True, False), (False, True), (False, False)):
        assert combination in seen, f"never observed {combination}"


def test_geometry_is_populated_on_most_rows(rows: list[dict[str, Any]]) -> None:
    """`count()` of a nullable column is the question here, deliberately.

    An all-NULL geometry is exactly what the time-base bug produced: rows
    appeared, `in_circle_*` was right because it comes from the roster, and
    every distance was quietly NULL.
    """
    with_geometry = sum(1 for r in rows if r["dist_to_white_edge_cm"] is not None)
    assert with_geometry / len(rows) > 0.5, (
        f"geometry present on only {with_geometry}/{len(rows)} rows — suspect a "
        f"time-base mismatch between Sample.t_ms (absolute) and PhaseChange.t_s "
        f"(relative)"
    )


def test_signed_edge_distance_matches_centre_and_radius(
    rows: list[dict[str, Any]],
) -> None:
    for r in rows:
        if (
            r["dist_to_white_edge_cm"] is None
            or r["dist_to_white_centre_cm"] is None
            or r["white_r_cm"] is None
        ):
            continue
        assert r["dist_to_white_edge_cm"] == pytest.approx(
            r["dist_to_white_centre_cm"] - r["white_r_cm"]
        )


def test_negative_edge_means_inside(rows: list[dict[str, Any]]) -> None:
    """Both signs occur, so the column orders the way the UI assumes."""
    edges = [r["dist_to_white_edge_cm"] for r in rows if r["dist_to_white_edge_cm"] is not None]
    assert any(e < 0 for e in edges), "nobody is ever inside the circle"
    assert any(e > 0 for e in edges), "nobody is ever outside the circle"


def test_sample_lag_is_bounded(rows: list[dict[str, Any]]) -> None:
    """A row with geometry read from a very old sample is worse than no row."""
    from pubg_dashboard.telemetry.zoneplay import MAX_SAMPLE_LAG_MS

    for r in rows:
        if r["sample_lag_ms"] is not None:
            assert r["sample_lag_ms"] <= MAX_SAMPLE_LAG_MS


def test_rows_are_unique_per_account_and_phase(parsed: list[Any]) -> None:
    """The primary key, asserted before Postgres has to.

    `LogPhaseChange` fires twice per phase, so a version that failed to fold
    the pair would emit two rows per account per phase and the insert would
    raise — but only on a real database, which is not where this is caught.
    """
    for result in parsed:
        keys = [(r["account_id"], r["phase"]) for r in result.zone_play_rows]
        assert len(keys) == len(set(keys)), result.match_id


def test_rows_cover_the_whole_lobby_not_just_tracked_players(
    parsed: list[Any],
) -> None:
    """Rows exist for every participant, which is what makes the lobby
    baseline free — the same reasoning `strategy_metrics` uses."""
    for result in parsed:
        if not result.zone_play_rows:
            continue
        accounts = {r["account_id"] for r in result.zone_play_rows}
        assert len(accounts) > 20, f"{result.match_id}: only {len(accounts)} accounts"


def test_a_phase_nobody_saw_produces_no_row(parsed: list[Any]) -> None:
    """Absent, not null-filled.

    "Dead before phase 6" and "alive outside the circle at phase 6" are
    different facts. A row of nulls would merge them and the in-circle rate at
    late phases would be computed over a denominator including the dead.
    """
    for result in parsed:
        rows = result.zone_play_rows
        if not rows:
            continue
        per_phase = collections.Counter(r["phase"] for r in rows)
        phases = sorted(per_phase)
        if len(phases) < 3:
            continue
        # The lobby shrinks, so later phases must have fewer rows than the
        # first. Equal counts would mean the dead are still being emitted.
        assert per_phase[phases[-1]] < per_phase[phases[0]], per_phase


def _phases(result: Any) -> list[Any]:
    """Re-derive the phase list from a parse result's world tracker.

    `ParseResult` does not carry the tracker, so this re-reads what the rows
    imply. Kept as a helper so the tests above read as assertions rather than
    as plumbing.
    """
    # Reconstruct from the rows: each phase contributes at most one announce
    # time and one close time, shared by every account in it.
    seen: dict[tuple[int, str], Any] = {}
    for row in result.zone_play_rows:
        phase = row["phase"]
        if row["announce_t_s"] is not None:
            seen[(phase, E.PHASE_ANNOUNCE)] = _Change(
                phase, E.PHASE_ANNOUNCE, row["announce_t_s"]
            )
        if row["close_t_s"] is not None:
            seen[(phase, E.PHASE_CLOSE)] = _Change(phase, E.PHASE_CLOSE, row["close_t_s"])
    return list(seen.values())


class _Change:
    __slots__ = ("kind", "phase", "t_s")

    def __init__(self, phase: int, kind: str, t_s: float) -> None:
        self.phase = phase
        self.kind = kind
        self.t_s = t_s
