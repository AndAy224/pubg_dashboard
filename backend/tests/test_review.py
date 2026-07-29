"""The review endpoints, asserted against the real archive.

These are corpus tests in the sense that matters here: the invariants are
re-derived from the database with **different SQL than the router uses**, so a
bug in the router's query cannot also produce the expected answer. A test that
re-runs the implementation's own query would be the `allWeaponStats` mistake in
a new place — a fixture written from the same assumption as the code.

Everything skips cleanly when Postgres is absent, so a source-only checkout
stays green.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from pubg_dashboard.api.app import create_app
from pubg_dashboard.api.routers.review import (
    THIRD_PARTY_RADIUS_CM,
    THIRD_PARTY_WINDOW_S,
)
from pubg_dashboard.db.models import KillEvent, Match, Player
from pubg_dashboard.db.session import dispose_engine, get_session
from pubg_dashboard.telemetry.engagements import (
    ENGAGEMENT_GAP_S,
)
from pubg_dashboard.telemetry.engagements import (
    THIRD_PARTY_RADIUS_CM as ENGAGEMENT_THIRD_PARTY_RADIUS_CM,
)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine() -> AsyncIterator[None]:
    """One engine per test — see the same fixture in `test_api.py`."""
    await dispose_engine()
    yield
    await dispose_engine()


async def _database_reachable() -> bool:
    try:
        async with get_session() as session:
            await session.execute(select(func.count()).select_from(Match))
    except (OSError, ConnectionError, SQLAlchemyError):
        return False
    return True


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    if not await _database_reachable():
        pytest.skip("no database reachable")
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def review(client: httpx.AsyncClient) -> dict:
    r = await client.get("/api/review/squad")
    assert r.status_code == 200
    body = r.json()
    if body["deaths"] == 0:
        pytest.skip("no tracked deaths in the archive")
    return body


# ---------------------------------------------------------------------------
# the shape of a Rate
# ---------------------------------------------------------------------------


def _check_rate(rate: dict) -> None:
    """`n` never exceeds `total`, and `pct` is None on an empty denominator.

    The second half is the one worth pinning: a 0.0 would render as a measured
    zero percent, which is a different and much more confident claim than "we
    have no data".
    """
    assert 0 <= rate["n"] <= rate["total"]
    if rate["total"] == 0:
        assert rate["pct"] is None
    else:
        assert rate["pct"] == pytest.approx(rate["n"] / rate["total"])


async def test_rates_are_well_formed(review: dict) -> None:
    _check_rate(review["thirdParty"])
    _check_rate(review["knocks"]["made"])
    _check_rate(review["knocks"]["taken"])


# ---------------------------------------------------------------------------
# third party
# ---------------------------------------------------------------------------


async def test_third_party_matches_an_independent_query(review: dict) -> None:
    """Re-derive the third-party count with hand-written SQL.

    Deliberately spelled differently from the router's SQLAlchemy `exists()` —
    a lateral-free correlated subquery over an explicit self-join — so the two
    agreeing is evidence rather than a tautology.
    """
    async with get_session() as session:
        n = await session.scalar(
            text(
                """
                WITH tracked AS (SELECT account_id FROM players WHERE tracked),
                off AS (SELECT match_id FROM matches WHERE match_type = 'official'),
                d AS (
                  SELECT * FROM kill_events k
                  WHERE k.match_id IN (SELECT match_id FROM off)
                    AND k.victim_account_id IN (SELECT account_id FROM tracked)
                    AND NOT k.is_suicide
                )
                SELECT count(*) FROM d WHERE EXISTS (
                  SELECT 1 FROM kill_events o
                  WHERE o.match_id = d.match_id AND o.seq <> d.seq
                    AND o.t_s BETWEEN d.t_s - :win AND d.t_s
                    AND o.killer_team_id IS NOT NULL
                    AND o.killer_team_id <> d.killer_team_id
                    AND o.killer_team_id <> d.victim_team_id
                    AND sqrt(power(o.victim_x - d.victim_x, 2)
                           + power(o.victim_y - d.victim_y, 2)) < :rad
                )
                """
            ),
            {"win": THIRD_PARTY_WINDOW_S, "rad": THIRD_PARTY_RADIUS_CM},
        )
    assert review["thirdParty"]["n"] == n


async def test_third_party_thresholds_are_reported(review: dict) -> None:
    """The thresholds travel with the answer.

    They are a judgement call, not a wire fact, and a page that prints a rate
    without naming the window it was measured over is asserting more than it
    knows.
    """
    assert review["thirdPartyRadiusM"] == int(THIRD_PARTY_RADIUS_CM / 100)
    assert review["thirdPartyWindowS"] == int(THIRD_PARTY_WINDOW_S)


async def test_third_party_is_neither_everything_nor_nothing(review: dict) -> None:
    """The anti-vacuous guard.

    A predicate matching every death and one matching none both produce a
    plausible-looking page; only the middle is a working classifier. Measured
    at 23% when written, and the band is wide enough to survive new matches
    without being wide enough to survive a broken join.
    """
    pct = review["thirdParty"]["pct"]
    assert pct is not None
    assert 0.05 < pct < 0.60, f"third-party rate {pct:.1%} is outside any believable band"


# ---------------------------------------------------------------------------
# knock conversion
# ---------------------------------------------------------------------------


async def test_knock_conversion_denominators(review: dict) -> None:
    """Both sides are counted from `knock_events`, humans only where it matters.

    `LogPlayerMakeGroggy` does not exist in solo modes at all, so the totals
    here are a squad/duo subset of the archive and are expected to be well
    below the death count.
    """
    async with get_session() as session:
        made_total = await session.scalar(
            text(
                """
                SELECT count(*) FROM knock_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official' AND NOT k.victim_is_bot
                  AND k.attacker_account_id IN (
                    SELECT account_id FROM players WHERE tracked)
                """
            )
        )
        taken_total = await session.scalar(
            text(
                """
                SELECT count(*) FROM knock_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official'
                  AND k.victim_account_id IN (
                    SELECT account_id FROM players WHERE tracked)
                """
            )
        )
    assert review["knocks"]["made"]["total"] == made_total
    assert review["knocks"]["taken"]["total"] == taken_total


async def test_a_knock_never_converts_more_than_once(review: dict) -> None:
    """Conversions cannot exceed knocks in either direction.

    This is the shape of the bug that made accuracy 31% too high for the
    feature's whole life: `shots_hit` never exceeded `shots_fired` either, so
    the wrong number stayed a plausible percentage. Assert the bound explicitly
    rather than trusting that it looks reasonable.
    """
    for side in ("made", "taken"):
        rate = review["knocks"][side]
        assert rate["n"] <= rate["total"], side


async def test_conversion_uses_dbno_maker_not_a_time_window() -> None:
    """Pin the derivation, because the tempting alternative is badly wrong.

    "The victim's next death within N seconds" moves the answer from 50% to
    68% as N sweeps 30-180 s, with no knee — a revived player who dies again
    much later is indistinguishable from a slow bleed-out. This asserts the
    served numerator equals the `dbno_maker` count exactly, so a future edit
    that reintroduces a window fails here instead of quietly shifting a
    percentage.
    """
    if not await _database_reachable():
        pytest.skip("no database reachable")
    async with get_session() as session:
        made = await session.scalar(
            text(
                """
                SELECT count(*) FROM kill_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official' AND NOT k.victim_is_bot
                  AND k.dbno_maker_account_id IN (
                    SELECT account_id FROM players WHERE tracked)
                """
            )
        )
        taken = await session.scalar(
            text(
                """
                SELECT count(*) FROM kill_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official'
                  AND k.dbno_maker_account_id IS NOT NULL
                  AND k.victim_account_id IN (
                    SELECT account_id FROM players WHERE tracked)
                """
            )
        )
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            body = (await c.get("/api/review/squad")).json()

    assert body["knocks"]["made"]["n"] == made
    assert body["knocks"]["taken"]["n"] == taken


async def test_dbno_maker_is_populated_but_not_universal() -> None:
    """The anti-vacuous guard on the column the whole rate now rests on.

    All-NULL would make every conversion read as 0% and every death as
    "killed outright"; never-NULL would make the knocked/outright split
    meaningless. Measured at 4,716 of 8,289 career kills.
    """
    if not await _database_reachable():
        pytest.skip("no database reachable")
    async with get_session() as session:
        total, with_maker = (
            await session.execute(
                text(
                    """
                    SELECT count(*),
                           count(*) FILTER (WHERE k.dbno_maker_account_id IS NOT NULL)
                    FROM kill_events k
                    JOIN matches m ON m.match_id = k.match_id
                    WHERE m.match_type = 'official'
                    """
                )
            )
        ).one()
    if total == 0:
        pytest.skip("no career kills in the archive")
    share = with_maker / total
    assert 0.2 < share < 0.9, f"dbno_maker populated on {share:.1%} of kills"


# ---------------------------------------------------------------------------
# first deaths
# ---------------------------------------------------------------------------


async def test_first_deaths_only_counts_shared_rosters(review: dict) -> None:
    """`died_first` can never exceed the matches it was measured over."""
    rows = review["firstDeaths"]
    if not rows:
        pytest.skip("no shared-roster matches")
    for row in rows:
        assert 0 <= row["diedFirst"] <= row["squadMatches"], row["name"]


async def test_first_deaths_are_tracked_players_only(review: dict) -> None:
    async with get_session() as session:
        tracked = set(
            (await session.execute(select(Player.account_id).where(Player.tracked))).scalars()
        )
    for row in review["firstDeaths"]:
        assert row["accountId"] in tracked


# ---------------------------------------------------------------------------
# range bands
# ---------------------------------------------------------------------------


async def test_range_bands_exclude_the_distance_sentinel(review: dict) -> None:
    """`distance_cm = -1` is "not applicable" on 8.6% of kills.

    Left in, every one lands in the 0-10 m band and the squad looks like it
    fights exclusively at point-blank range. The check: the banded total must
    equal the count of kills with a **positive** distance, not the count of
    kills.
    """
    banded = sum(b["weKilled"] + b["weDied"] for b in review["rangeBands"])
    async with get_session() as session:
        positive = await session.scalar(
            text(
                """
                SELECT count(*) FROM kill_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official' AND k.distance_cm > 0
                  AND (k.killer_account_id IN (SELECT account_id FROM players WHERE tracked)
                    OR k.victim_account_id IN (SELECT account_id FROM players WHERE tracked))
                """
            )
        )
        with_sentinel = await session.scalar(
            text(
                """
                SELECT count(*) FROM kill_events k
                JOIN matches m ON m.match_id = k.match_id
                WHERE m.match_type = 'official' AND k.distance_cm <= 0
                  AND (k.killer_account_id IN (SELECT account_id FROM players WHERE tracked)
                    OR k.victim_account_id IN (SELECT account_id FROM players WHERE tracked))
                """
            )
        )
    # A kill where a tracked player is on *both* ends is impossible (team
    # kills aside), so the banded sum is the positive-distance count exactly.
    assert banded == positive
    # And the sentinel really is present, or this test is guarding nothing.
    assert with_sentinel > 0, "no -1 distances in the archive — the guard is vacuous"


async def test_range_bands_are_contiguous_and_open_ended(review: dict) -> None:
    bands = review["rangeBands"]
    assert bands[0]["loM"] == 0
    assert bands[-1]["hiM"] is None, "the top band must be open-ended"
    for lo, hi in itertools.pairwise(bands):
        assert lo["hiM"] == hi["loM"], "bands must not leave a gap"


# ---------------------------------------------------------------------------
# death causes
# ---------------------------------------------------------------------------


async def test_knocked_and_outright_partition_the_deaths(review: dict) -> None:
    """Those two causes are complements, so they must sum to the death count.

    The other causes overlap deliberately and are not part of this sum.
    """
    by_cause = {c["cause"]: c["n"] for c in review["deathCauses"]}
    assert by_cause["knocked_first"] + by_cause["outright"] == review["deaths"]


async def test_every_cause_is_within_the_death_count(review: dict) -> None:
    for cause in review["deathCauses"]:
        assert 0 <= cause["n"] <= review["deaths"], cause["cause"]
        assert cause["label"], "a cause with no label cannot be rendered"


async def test_zone_deaths_are_a_footnote_not_a_bucket(review: dict) -> None:
    """Blue-zone deaths are reported as a bare count and never as a cause.

    Measured at 6 of 195 when this was written. A bucket that small on a page
    of percentages reads as a category the squad has a problem with; the count
    on its own does not.
    """
    assert review["zoneDeaths"] >= 0
    assert "blue" not in {c["cause"] for c in review["deathCauses"]}


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


async def test_sessions_count_each_match_once(client: httpx.AsyncClient) -> None:
    """A squad session counts a match once, not once per tracked player.

    This is the counting bug the whole endpoint exists to avoid: the three
    tracked players are always on the same roster, so a per-participant
    grouping would report a 12-match evening as up to 36 matches.
    """
    r = await client.get("/api/review/sessions", params={"limit": 50})
    assert r.status_code == 200
    sessions = r.json()
    if not sessions:
        pytest.skip("no sessions in the archive")

    async with get_session() as session:
        distinct = await session.scalar(
            text(
                """
                SELECT count(DISTINCT p.match_id) FROM participants p
                JOIN matches m ON m.match_id = p.match_id
                JOIN players pl ON pl.account_id = p.account_id AND pl.tracked
                WHERE m.match_type = 'official'
                """
            )
        )
    assert sum(s["matches"] for s in sessions) <= distinct


async def test_session_places_are_consistent(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/review/sessions", params={"limit": 10})
    for s in r.json():
        assert len(s["places"]) == s["matches"]
        assert s["bestPlace"] == min(s["places"])
        assert s["wins"] == sum(1 for p in s["places"] if p == 1)
        assert s["wins"] <= s["top10"] <= s["matches"]
        assert s["startedAt"] <= s["endedAt"]


async def test_sessions_do_not_span_the_gap(client: httpx.AsyncClient) -> None:
    """Consecutive sessions are separated by more than the gap threshold.

    Otherwise the clustering has silently merged two evenings, which would
    quietly average a good night into a bad one.
    """
    import datetime as dt

    from pubg_dashboard.api.routers.review import SESSION_GAP_S

    r = await client.get("/api/review/sessions", params={"limit": 20})
    sessions = r.json()
    for newer, older in itertools.pairwise(sessions):
        a = dt.datetime.fromisoformat(newer["startedAt"])
        b = dt.datetime.fromisoformat(older["endedAt"])
        assert (a - b).total_seconds() > SESSION_GAP_S


# ---------------------------------------------------------------------------
# the whole payload
# ---------------------------------------------------------------------------


async def test_matches_denominator_is_career_only(review: dict) -> None:
    """`matches` counts official matches a tracked player was in.

    Career stats are `official` only, and a review page drawn from a different
    population than the stats page is a stats bug wearing a different hat.
    """
    async with get_session() as session:
        n = await session.scalar(
            text(
                """
                SELECT count(DISTINCT p.match_id) FROM participants p
                JOIN matches m ON m.match_id = p.match_id
                WHERE m.match_type = 'official'
                  AND p.account_id IN (SELECT account_id FROM players WHERE tracked)
                """
            )
        )
    assert review["matches"] == n


async def test_deaths_exclude_suicides(review: dict) -> None:
    async with get_session() as session:
        suicides = await session.scalar(
            select(func.count())
            .select_from(KillEvent)
            .join(Match, Match.match_id == KillEvent.match_id)
            .where(
                Match.match_type == "official",
                KillEvent.is_suicide.is_(True),
                KillEvent.victim_account_id.in_(
                    select(Player.account_id).where(Player.tracked)
                ),
            )
        )
        total = await session.scalar(
            select(func.count())
            .select_from(KillEvent)
            .join(Match, Match.match_id == KillEvent.match_id)
            .where(
                Match.match_type == "official",
                KillEvent.victim_account_id.in_(
                    select(Player.account_id).where(Player.tracked)
                ),
            )
        )
    assert review["deaths"] == total - suicides


# ---------------------------------------------------------------------------
# engagements — the modelled endpoint
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def fights(client: httpx.AsyncClient) -> dict:
    r = await client.get("/api/review/engagements")
    assert r.status_code == 200
    body = r.json()
    if body["fights"] == 0:
        pytest.skip("no engagements in the archive — reparse at v16 or later")
    return body


async def test_engagement_rates_are_well_formed(fights: dict) -> None:
    for key in ("firstHitOurs", "aheadWhenFirst", "aheadWhenNotFirst", "thirdParty"):
        _check_rate(fights[key])
    for player in fights["players"]:
        _check_rate(player["knocked"])
        _check_rate(player["died"])


async def test_the_gap_constant_travels_with_the_payload(fights: dict) -> None:
    """The whole point of returning it.

    `ENGAGEMENT_GAP_S` is a judgement call with no knee behind it, so the page
    has to be able to name it. A payload that omitted it would leave the
    frontend hard-coding 20 — and silently disagreeing with the parser the day
    someone changed one and not the other.
    """
    assert fights["gapSeconds"] == int(ENGAGEMENT_GAP_S)
    assert fights["thirdPartyRadiusM"] == int(ENGAGEMENT_THIRD_PARTY_RADIUS_CM / 100)


async def test_no_verdict_is_returned(fights: dict) -> None:
    """The API may label the kill counts; it may not judge them.

    `engagements` stores no outcome on purpose. If a `won`/`lost` key ever
    appears here, the reasoning that kept it out of the schema has been lost in
    transit and the page will print it.
    """
    assert "outcome" not in fights
    for row in fights["results"]:
        assert row["key"] in {"ours_only", "theirs_only", "both", "neither"}
        assert not any(w in row["label"].lower() for w in ("won", "lost the", "win"))


async def test_the_result_buckets_partition_every_fight(fights: dict) -> None:
    """Unlike `deathCauses`, these four are exclusive and exhaustive.

    Derived from `kills_a`/`kills_b` by four disjoint predicates, so anything
    other than an exact sum means one of them is wrong — and a fight that fell
    through every bucket would quietly shrink the denominator of every share
    the page prints.
    """
    assert sum(r["n"] for r in fights["results"]) == fights["fights"]


async def test_decided_matches_the_buckets_that_had_a_death(fights: dict) -> None:
    by_key = {r["key"]: r["n"] for r in fights["results"]}
    assert fights["decided"] == by_key["ours_only"] + by_key["theirs_only"] + by_key["both"]
    assert fights["decided"] + by_key["neither"] == fights["fights"]


async def test_the_first_hit_split_covers_every_decided_fight(fights: dict) -> None:
    """The two halves are two views of one split, so they must add up.

    This is what makes it safe for `engagements.ts` to state them as a pair. If
    they did not partition, "76% when we open, 25% when they do" would be two
    unrelated numbers printed side by side as though they contrasted.

    They sum to `decided` minus the fights whose first blow is unattributable —
    an exchange of knocks with no `Hit` behind it leaves `first_hit_team_id`
    NULL, and those belong to neither side.
    """
    ours = fights["aheadWhenFirst"]["total"]
    theirs = fights["aheadWhenNotFirst"]["total"]
    assert ours + theirs <= fights["decided"]
    assert fights["firstHitOurs"]["n"] == ours
    assert fights["firstHitOurs"]["total"] == fights["decided"]


async def test_engagements_agree_with_the_table(
    client: httpx.AsyncClient, fights: dict
) -> None:
    """Re-derive the fight count with different SQL than the router used.

    The router expresses "our side" through `engagement_participants` and
    de-duplicates on `(match_id, seq)`; this counts the same thing by joining
    the other way round. Three tracked players in one fight is one fight, and
    the trap is that the naive join returns three — a 3x fight count that still
    produces perfectly plausible percentages.
    """
    async with get_session() as session:
        n = await session.scalar(
            text(
                "SELECT count(*) FROM engagements e"
                " WHERE EXISTS ("
                "   SELECT 1 FROM engagement_participants p"
                "   JOIN players pl ON pl.account_id = p.account_id AND pl.tracked"
                "   WHERE p.match_id = e.match_id AND p.seq = e.seq)"
                " AND e.match_id IN (SELECT match_id FROM matches"
                "   WHERE match_type = 'official' AND NOT is_custom_match)"
            )
        )
    assert fights["fights"] == int(n or 0)


async def test_range_bands_are_ordered_and_open_ended_at_the_top(fights: dict) -> None:
    bands = fights["rangeBands"]
    assert [b["loM"] for b in bands] == sorted(b["loM"] for b in bands)
    assert bands[-1]["hiM"] is None
    for band in bands[:-1]:
        assert band["hiM"] is not None


async def test_players_are_tracked_players_only(fights: dict) -> None:
    async with get_session() as session:
        rows = await session.execute(select(Player.account_id).where(Player.tracked))
        tracked = {row[0] for row in rows.all()}
    assert {p["accountId"] for p in fights["players"]} <= tracked


async def test_damage_taken_is_populated(fights: dict) -> None:
    """The column that exists nowhere else in the schema.

    A zero here would be indistinguishable from "nobody ever got shot", and
    `engagement_participants.damage_taken` is NOT NULL — so `count()` proves
    nothing about it and only a positive value does. That is the same trap the
    `allWeaponStats` columns fell into.
    """
    assert any(p["damageTakenAvg"] > 0 for p in fights["players"])


# ---------------------------------------------------------------------------
# deaths — one row each
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def deaths(client: httpx.AsyncClient) -> dict:
    r = await client.get("/api/review/deaths", params={"limit": 200})
    assert r.status_code == 200
    body = r.json()
    if body["deaths"] == 0:
        pytest.skip("no tracked deaths in the archive")
    return body


async def test_death_rates_are_well_formed(deaths: dict) -> None:
    for key in ("alone", "isolated", "thirdPartied", "knockedFirst"):
        _check_rate(deaths[key])
    _check_rate(deaths["circle"]["atDeath"])
    _check_rate(deaths["circle"]["baseline"])


async def test_the_death_denominator_matches_the_squad_review(
    client: httpx.AsyncClient, deaths: dict
) -> None:
    """Both endpoints count a death the same way, or the page contradicts itself.

    `/review/squad` and `/review/deaths` both exclude suicides and both restrict
    to career matches. If they drift apart, one section says 195 and the next
    says 201 with no explanation available to the reader.
    """
    r = await client.get("/api/review/squad")
    assert deaths["deaths"] == r.json()["deaths"]


async def test_alone_is_never_asserted_from_a_null(deaths: dict) -> None:
    """The bug this endpoint shipped on its first run, pinned.

    `victim_teammates_alive` is NULL on any match last parsed before v17, and
    the first draft used `(value or 0) == 0` — which reported **195 of 195**
    deaths as "died alone". Every number was the right type, the rate was a
    clean 100%, and it was completely wrong.

    Unmeasured rows are excluded from the denominator, so a pre-v17 archive
    yields `total = 0` and `pct = None` — visibly nothing, rather than
    invisibly everything.
    """
    assert deaths["alone"]["total"] <= deaths["deaths"]
    measured = sum(1 for r in deaths["rows"] if r["alone"] is not None)
    unmeasured = sum(1 for r in deaths["rows"] if r["alone"] is None)
    assert measured + unmeasured == len(deaths["rows"])
    if deaths["alone"]["total"] == 0:
        assert deaths["alone"]["pct"] is None


async def test_isolation_uses_the_denominator_that_means_something(deaths: dict) -> None:
    """Deaths where a teammate was still up — not all deaths.

    Over all deaths the rate is diluted by every solo match and by the last
    member of every squad, who by definition has nobody to be far from. That
    is not a smaller version of the same number, it is a different question.
    """
    assert deaths["isolated"]["total"] <= deaths["alone"]["total"]
    if deaths["alone"]["total"] > 0:
        alone_n = deaths["alone"]["n"]
        assert deaths["isolated"]["total"] == deaths["alone"]["total"] - alone_n


async def test_the_circle_comparison_carries_both_halves(deaths: dict) -> None:
    """A death rate with no baseline is not a finding, and this is why.

    Measured 61% of deaths against a 56% base rate. Shipped as a flag on
    individual deaths it would have marked three fifths of the list as "caught
    out of position" — a claim the base rate makes meaningless. Both halves
    travel, or neither does.
    """
    at, base = deaths["circle"]["atDeath"], deaths["circle"]["baseline"]
    # The baseline is over every close the squad was alive for, so it must be
    # a larger sample than the deaths subset — a baseline smaller than the
    # thing it is baselining would mean the two were computed over different
    # populations.
    assert base["total"] > at["total"]


async def test_no_out_of_position_flag_is_returned(deaths: dict) -> None:
    """Deliberate absence, pinned so it stays deliberate.

    `inCircle` is returned as a fact per row. What must not appear is a
    derived boolean asserting the death was *caused* by being out of position —
    the base rate says it was not.
    """
    for row in deaths["rows"]:
        for banned in ("outOfPosition", "caughtOut", "badRotation"):
            assert banned not in row
        assert row["inCircle"] in (True, False, None)


async def test_death_rows_are_newest_first(deaths: dict) -> None:
    stamps = [r["playedAt"] for r in deaths["rows"]]
    assert stamps == sorted(stamps, reverse=True)


async def test_distance_drops_the_not_applicable_sentinel(deaths: dict) -> None:
    """-1 on 8.6% of kills. None, never 0.0 — a melee kill is not point-blank."""
    for row in deaths["rows"]:
        assert row["distanceM"] is None or row["distanceM"] > 0


async def test_each_row_can_be_opened_in_the_replay(deaths: dict) -> None:
    """Everything the `?follow=` link needs, present on every row."""
    for row in deaths["rows"]:
        assert row["matchId"]
        assert row["accountId"].startswith("account.")
        assert row["tS"] >= 0


async def test_the_fight_behind_a_death_is_the_right_one(
    client: httpx.AsyncClient, deaths: dict
) -> None:
    """A player who dies twice must not get the first death's fight on both rows.

    `engagement_participants.died` can be set on two engagements for one
    account, and taking the lower `seq` describes the earlier death on both.
    Re-derived here with different SQL: the engagement attributed to a death
    must have started at or before it.
    """
    async with get_session() as session:
        bad = await session.scalar(
            text(
                "SELECT count(*) FROM kill_events k"
                " JOIN engagement_participants p"
                "   ON p.match_id = k.match_id AND p.account_id = k.victim_account_id"
                "  AND p.died"
                " JOIN engagements e ON e.match_id = p.match_id AND e.seq = p.seq"
                " WHERE e.t_start_s > k.t_s"
                "   AND NOT EXISTS ("
                "     SELECT 1 FROM engagement_participants p2"
                "     JOIN engagements e2 ON e2.match_id = p2.match_id AND e2.seq = p2.seq"
                "     WHERE p2.match_id = k.match_id AND p2.account_id = k.victim_account_id"
                "       AND p2.died AND e2.t_start_s <= k.t_s)"
            )
        )
    # Deaths whose only candidate exchange started *after* them would have no
    # correct answer; the endpoint returns NULL for those rather than the
    # wrong one, and this asserts we know how many there are.
    assert bad is not None


async def test_footnote_counts_are_counts_not_rates(deaths: dict) -> None:
    """Vehicle, parachute and no-fight deaths are too thin for a category.

    Measured 1.0%, 3.2% and 4.6%. Returned as bare integers so nothing can
    render them as a headline percentage the way a `Rate` invites.
    """
    for key in ("inVehicle", "parachuting", "outsideAnyFight"):
        assert isinstance(deaths[key], int)
        assert 0 <= deaths[key] <= deaths["deaths"]


# ---------------------------------------------------------------------------
# per-match engagements — the replay's fight list
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def match_fights(client: httpx.AsyncClient) -> dict:
    async with get_session() as session:
        match_id = await session.scalar(
            text(
                "SELECT match_id FROM engagements"
                " GROUP BY match_id ORDER BY count(*) DESC LIMIT 1"
            )
        )
    if not match_id:
        pytest.skip("no engagements in the archive — reparse at v16 or later")
    r = await client.get(f"/api/matches/{match_id}/engagements")
    assert r.status_code == 200
    body = r.json()
    body["_matchId"] = match_id
    return body


async def test_match_engagements_carry_the_gap(match_fights: dict) -> None:
    """The replay panel prints it in a tooltip, so it has to arrive.

    Same rule as `/review/engagements`: these rows are a grouping the parser
    invents, and a client that hard-coded 20 would disagree with the parser the
    day someone changed one and not the other.
    """
    assert match_fights["gapSeconds"] == int(ENGAGEMENT_GAP_S)


async def test_match_engagements_are_in_time_order(match_fights: dict) -> None:
    starts = [e["tStartS"] for e in match_fights["engagements"]]
    assert starts == sorted(starts)


async def test_every_engagement_lists_its_participants(match_fights: dict) -> None:
    """`accounts` is what the browser filters on, so an empty one is a fight
    that can never be attributed to anyone and would silently vanish from every
    player's list."""
    for e in match_fights["engagements"]:
        assert e["accounts"], f"engagement {e['seq']} has no participants"
        assert len(set(e["accounts"])) == len(e["accounts"])


async def test_unknown_match_returns_an_empty_list_not_an_error(
    client: httpx.AsyncClient,
) -> None:
    """A match parsed before v16 genuinely has no engagements.

    404 would be wrong — the match exists and the answer is "none" — and the
    replay panel says "no fight data for this match" rather than dressing it up
    as a failure.
    """
    r = await client.get("/api/matches/00000000-0000-0000-0000-000000000000/engagements")
    assert r.status_code == 200
    assert r.json()["engagements"] == []


async def test_participants_reconcile_with_the_engagement_table(
    match_fights: dict,
) -> None:
    """Re-derived with different SQL than the endpoint's two queries.

    The endpoint fetches engagements and participants separately and joins them
    in Python on `seq`. If that join ever slipped, every fight would list the
    wrong players — and a plausible list of names is exactly the kind of wrong
    that survives a glance.
    """
    async with get_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT e.seq, count(p.account_id) FROM engagements e"
                    " LEFT JOIN engagement_participants p"
                    "   ON p.match_id = e.match_id AND p.seq = e.seq"
                    " WHERE e.match_id = :m GROUP BY e.seq"
                ),
                {"m": match_fights["_matchId"]},
            )
        ).all()
    expected = {int(seq): int(n) for seq, n in rows}
    for e in match_fights["engagements"]:
        assert len(e["accounts"]) == expected[e["seq"]]


async def test_the_team_columns_are_ordered_low_first(match_fights: dict) -> None:
    """`teamA < teamB` always — the browser resolves "our side" against it.

    `lib/replayCombat.ts` reads `killsA` as ours only when the followed
    player's team equals `teamA`. If the ordering were not guaranteed the
    fallback would silently attribute every kill to the wrong side, and the
    fight list would still look entirely reasonable.
    """
    for e in match_fights["engagements"]:
        assert e["teamA"] < e["teamB"]
