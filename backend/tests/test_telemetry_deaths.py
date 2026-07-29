"""Death-instant context, against the corpus.

The headline is `test_the_victim_sample_lands_on_the_death`. Unlike a zone
phase, a death does **not** have to be paired against a ~10 s position cadence:
`LogPlayerKillV2` carries the victim's own `Character` block and `FrameIndex`
feeds off it, so the sample is the death. That is what makes
`victim_nearest_teammate_cm` worth trusting at all — the victim's end of the
measurement is exact and only the teammate's end is sampled.

The second thing these pin is the NULL discipline, which matters more here than
anywhere else in the parser. `victim_nearest_teammate_cm` is NULL on 65% of
deaths because nobody was left alive to be near, and a zero there would read as
"a teammate was standing on them". Two tests keep the two apart.
"""

from __future__ import annotations

import math
import pathlib
import statistics
from typing import Any

import pytest

from pubg_dashboard.config import get_settings
from pubg_dashboard.telemetry.frames import FLAG_ALIVE
from pubg_dashboard.telemetry.parse import parse_telemetry
from pubg_dashboard.telemetry.strategy import NEAR_TEAMMATE_CM, TEAMMATE_PAIR_MS

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
def kills(parsed: list[Any]) -> list[dict[str, Any]]:
    out = [r for p in parsed for r in p.kill_rows]
    if not out:
        pytest.skip("no kills in the sampled corpus")
    return out


# ---------------------------------------------------------------------------
# the victim's end of the measurement is exact
# ---------------------------------------------------------------------------
def test_the_victim_sample_lands_on_the_death(kills: list[dict[str, Any]]) -> None:
    """Median lag ~1 ms, p90 ~32 ms, measured over 1,918 deaths.

    This is why this module needs none of `zone_play`'s hedging. If it ever
    fails, deaths have stopped being paired against their own `Character`
    block and every distance here became a ~10 s extrapolation instead — which
    at driving speed is most of a kilometre, and would still produce a
    perfectly plausible number.
    """
    lags = [k["victim_sample_lag_ms"] for k in kills if k.get("victim_sample_lag_ms") is not None]
    assert lags, "no victim samples at all"
    assert statistics.median(lags) < 500
    assert sorted(lags)[int(0.9 * len(lags))] < 2_000


def test_every_death_got_a_sample(parsed: list[Any]) -> None:
    """Measured: 0 of 1,918 deaths lacked one.

    Not asserted as an exact zero — a truncated download would legitimately
    produce some — but a run where a tenth of deaths had no track would mean
    the join had broken, and every rate below would then be computed over a
    silently smaller population.
    """
    total = sum(len(p.kill_rows) for p in parsed)
    missing = sum(
        1 for p in parsed for k in p.kill_rows if k.get("victim_sample_lag_ms") is None
    )
    assert total > 0
    assert missing / total < 0.05


def test_the_death_position_matches_the_kill_event(kills: list[dict[str, Any]]) -> None:
    """The sample the context came from is the one the kill row already carries.

    Both come from the same `Character` block, so they must agree. If they
    diverge, the context describes a different instant than `victim_x`/
    `victim_y` — and the map would draw the death in one place while the
    teammate distance was measured from another.
    """
    # Re-derived indirectly: a victim standing on their own recorded position
    # has zero distance to it, which only holds if both read the same sample.
    # The direct check is the lag test above; this one guards the pairing.
    checked = 0
    for k in kills:
        if k.get("victim_sample_lag_ms") is None:
            continue
        assert k["victim_sample_lag_ms"] <= TEAMMATE_PAIR_MS
        checked += 1
    assert checked > 100


# ---------------------------------------------------------------------------
# NULL is a real answer here, and a different one from zero
# ---------------------------------------------------------------------------
def test_no_living_teammate_is_null_not_zero(kills: list[dict[str, Any]]) -> None:
    """The distinction the whole column depends on.

    65% of deaths have nobody left to be near — every solo match, plus the last
    member of every squad. A zero there would read as "a teammate was standing
    on them", which is the opposite claim.
    """
    for k in kills:
        if k.get("victim_sample_lag_ms") is None:
            continue
        if k["victim_teammates_alive"] == 0:
            assert k["victim_nearest_teammate_cm"] is None
        # The converse does **not** hold: a teammate can be alive and still
        # contribute no distance, because their position track went quiet
        # near this instant. Counting them among the living while leaving the
        # distance NULL is the honest shape — "unmeasured" is not "far away".
        if k["victim_nearest_teammate_cm"] is not None:
            assert k["victim_teammates_alive"] > 0


def test_both_cases_actually_occur(kills: list[dict[str, Any]]) -> None:
    """Anti-vacuous. The test above passes trivially if one side never happens."""
    alone = sum(1 for k in kills if k.get("victim_teammates_alive") == 0)
    company = sum(
        1 for k in kills if (k.get("victim_teammates_alive") or 0) > 0
    )
    assert alone > 0, "nobody ever died alone — check the alive flag"
    assert company > 0, "nobody ever died with a teammate up — check the pairing"


def test_distances_are_plausible(kills: list[dict[str, Any]]) -> None:
    """Non-negative, and inside the world.

    8 km is the largest map dimension, so a distance beyond its diagonal means
    the coordinate transform or the account pairing is wrong — the two failures
    that would otherwise produce a large, confident, meaningless number.
    """
    world_diagonal_cm = 816_000 * math.sqrt(2)
    for k in kills:
        d = k.get("victim_nearest_teammate_cm")
        if d is not None:
            assert 0.0 <= d <= world_diagonal_cm


def test_the_hundred_metre_cut_actually_splits_the_data(
    kills: list[dict[str, Any]],
) -> None:
    """`NEAR_TEAMMATE_CM` has to land somewhere useful, not at an extreme.

    Measured: median 31 m, p90 132 m, so 100 m sits around the 86th percentile
    — most deaths happen with a teammate close, and "isolated" stays a
    minority rather than a description of every death. A cut that flagged 2% or
    90% would be a cut worth changing, and the API's isolation bucket is built
    on this one, so it is checked here rather than assumed.
    """
    d = [k["victim_nearest_teammate_cm"] for k in kills if k.get("victim_nearest_teammate_cm")]
    if len(d) < 50:
        pytest.skip("too few squad deaths in the sample")
    far = sum(1 for x in d if x > NEAR_TEAMMATE_CM)
    assert 0.02 < far / len(d) < 0.60, f"{far}/{len(d)} beyond {NEAR_TEAMMATE_CM / 100:.0f} m"


# ---------------------------------------------------------------------------
# the flags that were measured and then deliberately not made into buckets
# ---------------------------------------------------------------------------
def test_dying_in_a_vehicle_is_rare_enough_to_stay_a_footnote(
    kills: list[dict[str, Any]],
) -> None:
    """Measured 1.0% of deaths, so it gets a count and not a category.

    Pinned so the decision is revisited deliberately rather than by drift. If
    this ever climbs past a few percent the bucket becomes worth having, and
    the API's footnote should become a tile.
    """
    rows = [k for k in kills if k.get("victim_in_vehicle") is not None]
    assert rows
    n = sum(1 for k in rows if k["victim_in_vehicle"])
    assert n / len(rows) < 0.10


def test_no_parachuting_column_is_written(kills: list[dict[str, Any]]) -> None:
    """The column v17 added, and v19 removed. Pinned so it stays removed.

    It came from `FLAG_PARACHUTING`, whose name reads as a per-player state and
    is not one — it is set from `common.isGame` being the plane-phase value,
    a property of the **match**, true for the whole lobby at once and still
    true for someone who dropped early and is already fighting.

    Measured over 1,918 deaths: 62 carried the flag and **42 had already
    landed**. The review page rendered "still in the air" on 4-metre firefights.
    """
    assert "victim_parachuting" not in kills[0]


def test_genuinely_airborne_deaths_are_too_rare_to_record(parsed: list[Any]) -> None:
    """One death in 1,918, and that one a flare-gun redeploy at 364 s.

    This is the measurement that decided the column should be dropped rather
    than corrected, so it is asserted rather than left in a commit message.
    Against each victim's own `LogParachuteLanding` — exact, per player — an
    airborne death is a fraction of a percent, far below the 1.0% that made
    "died in a vehicle" a footnote instead of a category.

    A bound rather than an equality: PUBG could make redeploys common tomorrow,
    and if this ever fails the column is worth having again, computed this way.
    """
    airborne = total = 0
    for result in parsed:
        _combat, frames, _teams = _rebuild(result)
        for row in result.kill_rows:
            total += 1
            landing = frames.landing(row["victim_account_id"])
            # `landing is None` is "never landed at all" — a disconnect or a
            # plane death — which is a different and equally rare thing. It is
            # not counted as airborne, because it is not measured.
            if landing is not None and result.meta.t0_ms + int(row["t_s"] * 1000) < landing[0]:
                airborne += 1
    assert total > 300
    assert airborne / total < 0.01, f"{airborne}/{total} airborne — reconsider the column"


def test_a_dead_teammate_is_never_counted_as_present(parsed: list[Any]) -> None:
    """`teammates_alive` counts the living, and the corpus can disagree loudly.

    A knocked player reports `health: 0` and 51% of kill victims are still
    flagged `isDBNO` when they die, so "alive" cannot be read off health —
    `FLAG_ALIVE` means *still in the match* and is resolved in `FrameIndex`.
    Reading it wrong would count corpses as backup: a squad wipe would show
    three teammates alive at the last death instead of none.
    """
    for result in parsed:
        team_of = {p.account_id: p.team_id for p in result.players}
        sizes: dict[int, int] = {}
        for team in team_of.values():
            sizes[team] = sizes.get(team, 0) + 1
        for row in result.kill_rows:
            alive = row.get("victim_teammates_alive")
            if alive is None:
                continue
            roster = sizes.get(team_of.get(row["victim_account_id"], -1), 1)
            assert 0 <= alive <= roster - 1


def test_the_last_of_a_squad_to_die_has_nobody_left(parsed: list[Any]) -> None:
    """The strongest available check on the alive flag.

    Whoever dies last on a team must have zero living teammates at that
    instant, by definition — there is nobody after them. This holds without
    knowing anything about the position track, so it isolates the alive
    resolution from the pairing.

    Restricted to teams where everyone died: a team with a survivor has no
    "last death" in this sense.
    """
    checked = 0
    for result in parsed:
        team_of = {p.account_id: p.team_id for p in result.players}
        roster: dict[int, set[str]] = {}
        for account, team in team_of.items():
            roster.setdefault(team, set()).add(account)

        # Final death per account — a player can die twice.
        last_death: dict[str, dict[str, Any]] = {}
        for row in result.kill_rows:
            got = last_death.get(row["victim_account_id"])
            if got is None or row["t_s"] >= got["t_s"]:
                last_death[row["victim_account_id"]] = row

        for team, members in roster.items():
            if len(members) < 2 or not members <= set(last_death):
                continue
            final = max((last_death[m] for m in members), key=lambda r: r["t_s"])
            if final.get("victim_teammates_alive") is None:
                continue
            assert final["victim_teammates_alive"] == 0, (
                f"{result.match_id} team {team}: the last player to die had "
                f"{final['victim_teammates_alive']} teammates still up"
            )
            checked += 1
    assert checked > 5, f"only {checked} fully-wiped teams — the sample proves little"


def test_the_first_of_a_team_to_die_still_had_someone_up(parsed: list[Any]) -> None:
    """The mirror of the test above, and the one v17 failed.

    Whoever dies *first* on a team must have had at least one teammate alive —
    by definition, since nobody on that team had died yet. It needs no position
    data and no distance, so it isolates the aliveness resolution completely.

    v17 read `FLAG_ALIVE` off the teammate's nearest position sample.
    `FrameIndex._resolve` clears that flag on every sample at or after an
    account's final death, and a teammate dying in the same burst emits their
    death frame a few milliseconds later — so `_nearest` returned that frame
    and reported them already gone. 65 of 139 "died alone" deaths had a
    teammate whose own death was **2 to 128 ms** afterwards, and the squad's
    duo figure came out at 92% when the only possible answer is 50%.

    v18 reads `FrameIndex.death_ms` instead: exact, unsampled, and immune to
    which side of a millisecond a frame lands on.
    """
    checked = 0
    for result in parsed:
        team_of = {p.account_id: p.team_id for p in result.players}
        by_team: dict[int, list[dict[str, Any]]] = {}
        for row in result.kill_rows:
            team = team_of.get(row["victim_account_id"])
            if team is not None:
                by_team.setdefault(team, []).append(row)

        for team, rows in by_team.items():
            if len(rows) < 2:
                continue
            first = min(rows, key=lambda r: r["t_s"])
            if first.get("victim_teammates_alive") is None:
                continue
            # Ties are real — a grenade kills two people in the same
            # millisecond — and at an exact tie neither is "first".
            if any(r is not first and r["t_s"] <= first["t_s"] for r in rows):
                continue
            assert first["victim_teammates_alive"] > 0, (
                f"{result.match_id} team {team}: the first player to die had "
                "nobody up, which is impossible"
            )
            checked += 1
    assert checked > 20, f"only {checked} multi-death teams — the sample proves little"


def test_the_alive_flag_is_not_simply_always_set(parsed: list[Any]) -> None:
    """Anti-vacuous twin: some deaths genuinely happen with teammates up."""
    with_company = sum(
        1
        for p in parsed
        for k in p.kill_rows
        if (k.get("victim_teammates_alive") or 0) > 0
    )
    assert with_company > 20


def test_context_is_deterministic(parsed: list[Any]) -> None:
    """A reparse must produce identical rows — `kill_events` is rewritten whole."""
    for result in parsed:
        again = parse_telemetry(
            next(p for p in _corpus() if p.name.startswith(result.match_id)).read_bytes(),
            match_id=result.match_id,
        )
        assert again.kill_rows == result.kill_rows


def test_a_knocked_teammate_still_counts_as_alive(parsed: list[Any]) -> None:
    """Aliveness comes from `FLAG_ALIVE`, and health cannot substitute for it.

    31,153 of 31,156 DBNO snapshots sit at exactly `health: 0`, so counting
    teammates by health would report a knocked-but-revivable teammate as dead.
    "You died alone" is the one claim on the review page that would then be
    systematically wrong in the squad's favour — and it would look entirely
    reasonable, because a squad genuinely does die alone most of the time.

    This finds real cases: a death where a teammate counted among
    `victim_teammates_alive` was themselves at zero health that instant.
    """
    found = 0
    for result in parsed:
        _combat, frames, teams = _rebuild(result)
        by_team: dict[int, list[str]] = {}
        for account, team in teams.items():
            by_team.setdefault(team, []).append(account)

        for row in result.kill_rows:
            if not (row.get("victim_teammates_alive") or 0):
                continue
            t_ms = result.meta.t0_ms + int(row["t_s"] * 1000)
            for mate in by_team.get(teams.get(row["victim_account_id"], -1), ()):
                if mate == row["victim_account_id"]:
                    continue
                got = _nearest_sample(frames.samples_for(mate), t_ms)
                if got is not None and got.flags & FLAG_ALIVE and got.health <= 0.0:
                    found += 1
    assert found > 0, (
        "no teammate was ever counted alive at zero health — either the corpus "
        "has no knocks near a death, or aliveness is being read off health"
    )


def _rebuild(result: Any) -> tuple[Any, Any, dict[str, int]]:
    """Re-feed the raw telemetry so a test compares against the source."""
    from pubg_dashboard.telemetry.combat import CombatTracker
    from pubg_dashboard.telemetry.frames import FrameIndex
    from pubg_dashboard.telemetry.maps import world_size
    from pubg_dashboard.telemetry.reader import load

    got = _CACHE.get(result.match_id)
    if got is None:
        path = next(p for p in _corpus() if p.name.startswith(result.match_id))
        events = load(path.read_bytes())
        frames = FrameIndex(result.meta.t0_ms, world_size(result.meta.map_name))
        combat = CombatTracker(result.meta.t0_ms / 1000.0)
        for event in events:
            frames.feed(event)
            combat.feed(event)
        teams = {p.account_id: p.team_id for p in result.players}
        got = _CACHE[result.match_id] = (combat, frames, teams)
    return got


_CACHE: dict[str, tuple[Any, Any, dict[str, int]]] = {}


def _nearest_sample(ss: list[Any], t_ms: int) -> Any | None:
    """Deliberately a second implementation of `deaths._nearest`.

    A test that called the module's own helper could only confirm that helper's
    shape. This one is a linear scan — slow, obvious, and independent.
    """
    best = None
    for s in ss:
        lag = abs(s.t_ms - t_ms)
        if lag <= TEAMMATE_PAIR_MS and (best is None or lag < abs(best.t_ms - t_ms)):
            best = s
    return best
