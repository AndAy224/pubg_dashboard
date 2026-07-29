"""The engagement model, checked against the corpus.

This module is testing a **model, not a reading**, which changes what a test
here can be worth. `test_roster_agrees_with_the_geometry` in the zone-play
suite compares two independent event streams and either they agree or the
transform is wrong. Nothing plays that role for an engagement: PUBG does not
record fights, so there is no ground truth to check the grouping against, and
no test below can tell you the grouping is *right*.

What these can do, and do:

* pin the arithmetic — the two sides of an engagement must sum to its totals,
  and every cross-team kill must be accounted for exactly once
  (`test_participant_rows_reconcile`, `test_every_cross_team_kill_is_accounted_for`);
* pin the invariants the grouping claims — no engagement may exceed the gap
  between consecutive events, `team_a < team_b`, `seq` in time order;
* pin **determinism**, which for a modelled output is the property most likely
  to break silently and the one a reparse depends on;
* pin the thing the model exists to fix — `test_kills_arrive_long_after_the_last_hit`
  asserts that bleed-out deaths really are far from the exchange, so the
  attach rules are still earning their place rather than sitting inert.

`test_the_gap_has_no_knee` is the honesty test: it re-runs the sweep and fails
if a knee ever appears. If one does, the constant stops being arbitrary and
this module's docstrings need rewriting — that is worth being told about.
"""

from __future__ import annotations

import collections
import itertools
import math
import pathlib
import statistics
from typing import Any

import pytest

from pubg_dashboard.config import get_settings
from pubg_dashboard.telemetry.combat import CombatTracker
from pubg_dashboard.telemetry.engagements import (
    ENGAGEMENT_GAP_S,
    THIRD_PARTY_RADIUS_CM,
    compute_engagements,
)
from pubg_dashboard.telemetry.parse import parse_telemetry
from pubg_dashboard.telemetry.reader import load

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
    out = [r for p in parsed for r in p.engagement_rows]
    if not out:
        pytest.skip("no engagements in the sampled corpus")
    return out


@pytest.fixture(scope="module")
def parts(parsed: list[Any]) -> list[dict[str, Any]]:
    return [r for p in parsed for r in p.engagement_participant_rows]


# ---------------------------------------------------------------------------
# arithmetic — the two sides must add up
# ---------------------------------------------------------------------------
def test_participant_rows_reconcile(parsed: list[Any]) -> None:
    """Every engagement's per-player rows sum to its own header.

    This is the check that a per-player table cannot quietly drift from the
    aggregate it hangs off. `allWeaponStats` failed exactly this way for the
    feature's whole life and nothing noticed, because both halves were wrong in
    the same direction.

    Hits are asserted from **both** ends: dealt and taken must each equal the
    engagement total, which they only can if every hit found two actors.
    """
    checked = 0
    for result in parsed:
        by_seq: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        for row in result.engagement_participant_rows:
            by_seq[row["seq"]].append(row)

        for eng in result.engagement_rows:
            ps = by_seq[eng["seq"]]
            assert ps, f"{eng['seq']} has no participants"
            hits = eng["hits_a"] + eng["hits_b"]
            assert sum(p["hits_dealt"] for p in ps) == hits
            assert sum(p["hits_taken"] for p in ps) == hits
            assert sum(p["knocks"] for p in ps) == eng["knocks_a"] + eng["knocks_b"]
            assert sum(p["kills"] for p in ps) == eng["kills_a"] + eng["kills_b"]
            assert math.isclose(
                sum(p["damage_dealt"] for p in ps),
                eng["dmg_a_to_b"] + eng["dmg_b_to_a"],
                rel_tol=1e-9,
            )
            assert math.isclose(
                sum(p["damage_taken"] for p in ps),
                sum(p["damage_dealt"] for p in ps),
                rel_tol=1e-9,
            )
            # Nobody from a third team may appear in the rows. A participant
            # row is what "who was in this fight" is answered from, so a
            # stray account would put a stranger in someone's fight review.
            assert {p["team_id"] for p in ps} <= {eng["team_a"], eng["team_b"]}
            checked += 1
    assert checked > 100, f"only {checked} engagements — the sample proves little"


def test_every_cross_team_kill_is_accounted_for(parsed: list[Any]) -> None:
    """Attached + unattached == every cross-team kill. No third bucket.

    A kill that vanished between `kill_events` and `engagements` would make the
    fight review quietly kinder than the match: fights we lost would be missing
    rather than wrong, which is the harder failure to spot.
    """
    for result in parsed:
        expected = sum(
            1
            for k in _kills(result)
            if k.killer_account_id
            and not k.is_suicide
            and not k.is_team_kill
            and _teams(result).get(k.killer_account_id) is not None
            and _teams(result).get(k.victim_account_id) is not None
            and _teams(result)[k.killer_account_id] != _teams(result)[k.victim_account_id]
        )
        attached = sum(e["kills_a"] + e["kills_b"] for e in result.engagement_rows)
        assert attached + result.unattached_kills == expected


def test_unattached_kills_are_a_small_minority(parsed: list[Any]) -> None:
    """Measured at 1.3% of cross-team kills across 25 matches.

    A bound rather than an equality: this is a property of PUBG's damage
    attribution, not of our arithmetic, and it will move. Ten percent would
    mean the attach rules had stopped working; zero would be as suspicious,
    because the corpus does contain kills whose credited killer never landed an
    attributed hit on the victim.
    """
    attached = sum(e["kills_a"] + e["kills_b"] for p in parsed for e in p.engagement_rows)
    unattached = sum(p.unattached_kills for p in parsed)
    assert attached > 0
    assert unattached / (attached + unattached) < 0.10


# ---------------------------------------------------------------------------
# the invariants the grouping itself claims
# ---------------------------------------------------------------------------
def test_no_exchange_contains_a_silence_longer_than_the_gap(parsed: list[Any]) -> None:
    """The defining property, re-derived from the raw hits and knocks.

    Rebuilt here from `CombatTracker` rather than read off the rows, so this
    fails if segmentation ever stops doing what its name says — a longer
    silence inside one engagement means two fights were merged into one, and
    every per-fight rate would be computed over the wrong denominator.
    """
    for result in parsed:
        teams = _teams(result)
        by_pair: dict[tuple[int, int], list[float]] = collections.defaultdict(list)
        combat = _combat(result)
        for hit in combat.hits:
            pair = _pair(teams, hit.attacker_account_id, hit.victim_account_id)
            if pair:
                by_pair[pair].append(hit.t_s)
        for knock in combat.knocks:
            if not knock.attacker_account_id:
                continue
            pair = _pair(teams, knock.attacker_account_id, knock.victim_account_id)
            if pair:
                by_pair[pair].append(knock.t_s)

        for eng in result.engagement_rows:
            inside = sorted(
                t
                for t in by_pair[(eng["team_a"], eng["team_b"])]
                if eng["t_start_s"] <= t <= eng["t_end_s"]
            )
            gaps = [b - a for a, b in itertools.pairwise(inside)]
            assert not gaps or max(gaps) <= ENGAGEMENT_GAP_S + 1e-6


def test_team_pairs_are_ordered_and_distinct(rows: list[dict[str, Any]]) -> None:
    """`team_a < team_b`, always.

    Without it the same pair has two representations and `(team_a, team_b)`
    stops being a group-by key — an aggregate over "fights against team 14"
    would silently see half of them.
    """
    for row in rows:
        assert row["team_a"] < row["team_b"]


def test_seq_is_dense_and_in_start_order(parsed: list[Any]) -> None:
    """`seq` is half a primary key that a reparse rewrites wholesale."""
    for result in parsed:
        seqs = [e["seq"] for e in result.engagement_rows]
        assert seqs == list(range(len(seqs)))
        starts = [e["t_start_s"] for e in result.engagement_rows]
        assert starts == sorted(starts)


def test_the_output_is_deterministic(parsed: list[Any]) -> None:
    """Recomputing from the same tracker must give byte-identical rows.

    For a modelled output this matters more than for a read one. The stream is
    two concatenated lists sorted by time, hits and knocks share timestamps
    constantly, and Python's sort is only stable with respect to the list it is
    handed — so without the explicit `(t, kind, index)` tiebreak a segment
    boundary could fall differently between two parses of the same file, and
    the reparse would rewrite `seq` to mean something else.
    """
    for result in parsed:
        again = compute_engagements(
            match_id=result.match_id, combat=_combat(result), teams=_teams(result)
        )
        assert again[0] == result.engagement_rows
        assert again[1] == result.engagement_participant_rows
        assert again[2] == result.unattached_kills


# ---------------------------------------------------------------------------
# the reason the attach rules exist
# ---------------------------------------------------------------------------
def test_kills_arrive_long_after_the_last_hit(parsed: list[Any]) -> None:
    """Bleed-outs are real, and far enough away that segmentation would lose them.

    `Damage_DBNO` ticks are self-attributed, so `CombatTracker` drops them as
    self-damage and a player who is knocked, crawls and runs out produces no
    hit between the knock and the death. Measured across 25 matches: on 16% of
    cross-team kills the credited killer's last attributed hit on that victim
    is 20 s or more before the death, with a median of 8 s past the end of the
    exchange.

    If this ever fails, the attach rules have become dead code and the module
    docstring's justification for them is wrong — which is worth knowing
    before someone simplifies them away.
    """
    lags: list[float] = []
    for result in parsed:
        teams = _teams(result)
        combat = _combat(result)
        last: dict[tuple[str, str], float] = {}
        for hit in combat.hits:
            last[(hit.attacker_account_id, hit.victim_account_id)] = hit.t_s
        for kill in combat.kills:
            if not kill.killer_account_id or kill.is_suicide or kill.is_team_kill:
                continue
            if not _pair(teams, kill.killer_account_id, kill.victim_account_id):
                continue
            seen = last.get((kill.killer_account_id, kill.victim_account_id))
            if seen is not None:
                lags.append(kill.t_s - seen)

    assert lags, "no cross-team kills at all in the sample"
    far = [x for x in lags if x > ENGAGEMENT_GAP_S]
    assert far, "no kill lands outside the gap — the attach rules do nothing here"
    assert max(far) > 30.0, f"longest lag only {max(far):.1f}s"


def test_a_knocked_player_is_not_always_a_dead_one(parts: list[dict[str, Any]]) -> None:
    """`was_knocked` and `died` are separate columns because they differ.

    39% of knocks against the squad end in a revive. Collapsing the two would
    make every knock a death and overstate how badly fights went.
    """
    knocked = [p for p in parts if p["was_knocked"]]
    assert knocked, "no knocks in the sample"
    survived = [p for p in knocked if not p["died"]]
    assert survived, "every knocked player died — check the attach rules"


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def test_the_fight_centre_is_equidistant_from_both_sides(parsed: list[Any]) -> None:
    """The centre sits the same distance from the shooters as from the targets.

    This is the test that a victim-only centroid fails and a bounding-box check
    does not: both land inside the fight, but only the symmetric one is the
    same distance from each end. At 300 m a victim-only centroid sits on top of
    the team that did the dying, so "where our fights happen" would draw
    somewhere plausible and wrong.

    Exact rather than approximate, because one attacker and one victim exist
    per hit — the two means have equal weight, so the midpoint is *the*
    midpoint.
    """
    checked = 0
    for result in parsed:
        for eng, seg_hits in _hits_by_seq(result):
            if eng["x"] is None or not seg_hits:
                continue
            n = len(seg_hits)
            att = (
                sum(h.attacker_x for h in seg_hits) / n,
                sum(h.attacker_y for h in seg_hits) / n,
            )
            vic = (
                sum(h.victim_x for h in seg_hits) / n,
                sum(h.victim_y for h in seg_hits) / n,
            )
            centre = (eng["x"], eng["y"])
            assert math.isclose(
                math.dist(centre, att), math.dist(centre, vic), abs_tol=1.0
            )
            # ...and inside the fight, not merely balanced about it.
            xs = [h.attacker_x for h in seg_hits] + [h.victim_x for h in seg_hits]
            ys = [h.attacker_y for h in seg_hits] + [h.victim_y for h in seg_hits]
            assert min(xs) <= centre[0] <= max(xs)
            assert min(ys) <= centre[1] <= max(ys)
            checked += 1
    assert checked > 100


def test_min_range_never_exceeds_the_opening_range(rows: list[dict[str, Any]]) -> None:
    """`min_range_cm` is a minimum over the same hits the first one came from."""
    for row in rows:
        if row["min_range_cm"] is not None and row["first_hit_range_cm"] is not None:
            assert row["min_range_cm"] <= row["first_hit_range_cm"] + 1e-6


def test_third_parties_are_close_and_are_a_third_team(parsed: list[Any]) -> None:
    """A third party is a *third* team, nearby, at the same time.

    The team-overlap half is what makes it a third party rather than an
    unrelated fight in the same town, and the radius is what stops a four-man
    squad fighting two teams 800 m apart from counting as one.
    """
    marked = 0
    for result in parsed:
        engs = result.engagement_rows
        for eng in engs:
            team = eng["third_party_team_id"]
            if team is None:
                continue
            marked += 1
            assert team not in (eng["team_a"], eng["team_b"])
            overlapping = [
                o
                for o in engs
                if o["seq"] != eng["seq"]
                and team in (o["team_a"], o["team_b"])
                and len({o["team_a"], o["team_b"]} & {eng["team_a"], eng["team_b"]}) == 1
                and not (o["t_end_s"] < eng["t_start_s"] or o["t_start_s"] > eng["t_end_s"])
                and o["x"] is not None
                and eng["x"] is not None
                and math.dist((eng["x"], eng["y"]), (o["x"], o["y"])) <= THIRD_PARTY_RADIUS_CM
            ]
            assert overlapping, f"{eng['seq']} names team {team} with no fight to point at"
    assert marked > 0, "no third parties at all — measured at ~13%"


def test_third_parties_are_a_minority(rows: list[dict[str, Any]]) -> None:
    """Measured 12.9% at 200 m over 25 matches.

    A loose upper bound. If most fights were flagged the column would have
    stopped distinguishing anything, which is the failure mode a radius
    threshold has.
    """
    marked = sum(1 for r in rows if r["third_party_team_id"] is not None)
    assert 0 < marked / len(rows) < 0.40


# ---------------------------------------------------------------------------
# honesty
# ---------------------------------------------------------------------------
def test_the_gap_has_no_knee(parsed: list[Any]) -> None:
    """Re-run the sweep. If a knee appears, the constant stops being arbitrary.

    Measured over 25 matches, the engagement count decays smoothly from 4,559
    at 5 s to 1,797 at 120 s with no step anywhere. That is why
    `ENGAGEMENT_GAP_S` is documented as a judgement call and reported to the
    client rather than presented as a discovered boundary.

    "No knee" is operationalised as: no single step in the sweep removes more
    than 40% of the engagements remaining at that point. A real fight length
    would show up as one step doing most of the work.
    """
    gaps = (5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0)
    counts = [
        sum(len(_segment_at(result, gap)) for result in parsed) for gap in gaps
    ]
    assert counts == sorted(counts, reverse=True), counts
    drops = [
        (a - b) / a for a, b in itertools.pairwise(counts)
    ]
    assert max(drops) < 0.40, f"a knee appeared: {list(zip(gaps, counts, strict=False))}"


def test_the_gap_actually_changes_the_answer(parsed: list[Any]) -> None:
    """The anti-vacuous twin of the test above.

    A sweep with no knee is only interesting if the parameter matters at all.
    Measured, 20 s and 30 s differ by 13%; if they ever stopped differing, the
    warnings this module carries would be noise and the constant could go.
    """
    at20 = sum(len(_segment_at(r, 20.0)) for r in parsed)
    at30 = sum(len(_segment_at(r, 30.0)) for r in parsed)
    assert at20 > at30 * 1.05


def test_no_outcome_verdict_is_stored(rows: list[dict[str, Any]]) -> None:
    """Deliberate absence, pinned so it stays deliberate.

    "Won" and "lost" are readings of the kill counts, not facts about the
    fight — a squad that killed two and lost three to a third party did not
    obviously lose to the team named in the row. Naming the verdict at query
    time keeps the reasoning next to it.
    """
    for name in ("outcome", "result", "won", "lost"):
        assert name not in rows[0]


def test_engagements_stay_a_manageable_size(parsed: list[Any]) -> None:
    """~120 engagements and ~340 participant rows per match, measured.

    A bound, not an equality. This exists because both tables grow per match
    forever and nothing else would notice a segmentation change that produced
    thousands per match until the database did.
    """
    for result in parsed:
        assert len(result.engagement_rows) < 600
        assert len(result.engagement_participant_rows) < 3000


def test_most_fights_are_small(rows: list[dict[str, Any]]) -> None:
    """Median 4 events, and a third of exchanges are one side landing hits.

    Stated as a test because it is the fact most likely to be forgotten when
    reading the word "engagement": most of these are not squad fights, they are
    somebody taking a couple of shots at range. Any page rendering a count of
    them has to say so.
    """
    two_way = [r for r in rows if r["hits_a"] > 0 and r["hits_b"] > 0]
    assert len(two_way) / len(rows) < 0.5


# ---------------------------------------------------------------------------
# helpers — these re-derive from the raw stream rather than trusting the rows
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[CombatTracker, dict[str, int]]] = {}


def _rebuild(result: Any) -> tuple[CombatTracker, dict[str, int]]:
    """Re-feed the raw telemetry, so tests compare against the source.

    Cached per match id: five matches at ~37k events each is slow enough to
    matter across a dozen tests, and the trackers are read-only here.
    """
    got = _CACHE.get(result.match_id)
    if got is None:
        path = next(
            p for p in _corpus() if p.name.startswith(result.match_id)
        )
        events = load(path.read_bytes())
        combat = CombatTracker(result.meta.t0_ms / 1000.0)
        for event in events:
            combat.feed(event)
        teams = {p.account_id: p.team_id for p in result.players}
        got = _CACHE[result.match_id] = (combat, teams)
    return got


def _combat(result: Any) -> CombatTracker:
    return _rebuild(result)[0]


def _teams(result: Any) -> dict[str, int]:
    return _rebuild(result)[1]


def _kills(result: Any) -> list[Any]:
    return _combat(result).kills


def _pair(teams: dict[str, int], a: str | None, b: str) -> tuple[int, int] | None:
    ta, tb = teams.get(a or ""), teams.get(b)
    if ta is None or tb is None or ta == tb:
        return None
    return (ta, tb) if ta < tb else (tb, ta)


def _hits_by_seq(result: Any) -> list[tuple[dict[str, Any], list[Any]]]:
    """Pair each engagement row back up with the hits that fall inside it."""
    teams = _teams(result)
    out = []
    for eng in result.engagement_rows:
        pair = (eng["team_a"], eng["team_b"])
        out.append(
            (
                eng,
                [
                    h
                    for h in _combat(result).hits
                    if eng["t_start_s"] <= h.t_s <= eng["t_end_s"]
                    and _pair(teams, h.attacker_account_id, h.victim_account_id) == pair
                ],
            )
        )
    return out


def _segment_at(result: Any, gap: float) -> list[tuple[int, int, float]]:
    """Segment one match's cross-team stream at an arbitrary gap.

    Deliberately a second implementation rather than a call into the module
    with a patched constant: a sweep that shares code with the thing it is
    measuring can only ever confirm that code's own shape.
    """
    teams = _teams(result)
    combat = _combat(result)
    stream: list[tuple[float, tuple[int, int]]] = []
    for hit in combat.hits:
        pair = _pair(teams, hit.attacker_account_id, hit.victim_account_id)
        if pair:
            stream.append((hit.t_s, pair))
    for knock in combat.knocks:
        pair = _pair(teams, knock.attacker_account_id, knock.victim_account_id)
        if pair:
            stream.append((knock.t_s, pair))
    stream.sort()

    out: list[tuple[int, int, float]] = []
    last: dict[tuple[int, int], float] = {}
    for t_s, pair in stream:
        prev = last.get(pair)
        if prev is None or t_s - prev > gap:
            out.append((pair[0], pair[1], t_s))
        last[pair] = t_s
    return out


def test_median_engagement_is_short(rows: list[dict[str, Any]]) -> None:
    """Median duration ~2 s, p90 ~23 s. Sanity on the time axis.

    A median in the minutes would mean the gap was merging a whole match's
    skirmishes with one team into a single row.
    """
    durations = [r["t_end_s"] - r["t_start_s"] for r in rows]
    assert statistics.median(durations) < 30.0
    assert max(durations) < 600.0
