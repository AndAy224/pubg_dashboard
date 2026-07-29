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
