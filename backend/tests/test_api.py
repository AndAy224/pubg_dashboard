"""API surface, exercised against the real ingested archive.

These run through `httpx.ASGITransport` — no socket, no uvicorn — but against
the live Postgres and object storage, because the interesting failures are in
the queries and the serialisation, not in the routing.
"""

from __future__ import annotations

import base64
import gzip
from array import array
from collections.abc import AsyncIterator

import httpx
import msgpack
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from pubg_dashboard.api.app import create_app
from pubg_dashboard.db.models import Match, Player
from pubg_dashboard.db.session import dispose_engine, get_session


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine() -> AsyncIterator[None]:
    """One engine per test, bound to that test's event loop.

    `db.session` caches the engine process-wide, and `asyncio_mode = auto`
    gives every test its own loop — so without this the second test onward gets
    a pooled connection attached to a loop that has already closed, and fails
    with "attached to a different loop". Disposing around each test is exactly
    the case `dispose_engine` documents.
    """
    await dispose_engine()
    yield
    await dispose_engine()


async def _database_reachable() -> bool:
    try:
        async with get_session() as session:
            await session.execute(select(func.count()).select_from(Match))
    except (OSError, ConnectionError, SQLAlchemyError):
        # A genuinely absent database — the only thing worth skipping for.
        # Anything else is a real failure and must not be swallowed as "no db".
        return False
    return True


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    if not await _database_reachable():
        pytest.skip("no database reachable")

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def a_match() -> str:
    if not await _database_reachable():
        pytest.skip("no database reachable")
    async with get_session() as session:
        mid = await session.scalar(
            select(Match.match_id).where(Match.replay_key.is_not(None)).limit(1)
        )
    if not mid:
        pytest.skip("no parsed match with a replay bundle")
    return mid


@pytest_asyncio.fixture
async def a_tracked_player() -> str:
    if not await _database_reachable():
        pytest.skip("no database reachable")
    async with get_session() as session:
        pid = await session.scalar(select(Player.account_id).where(Player.tracked).limit(1))
    if not pid:
        pytest.skip("no tracked players")
    return pid


# ---------------------------------------------------------------------------
# health / maps
# ---------------------------------------------------------------------------


async def test_health(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] is True
    assert body["matches"] >= 0
    assert "pollerLagS" in body, "the number that warns about permanent data loss"


async def test_responses_are_camel_case(client: httpx.AsyncClient) -> None:
    """The wire contract is camelCase; snake_case would leak Python style."""
    body = (await client.get("/api/health")).json()
    assert "queuePending" in body
    assert "queue_pending" not in body


async def test_maps_expose_the_image_scale_correction(client: httpx.AsyncClient) -> None:
    """8160/8192 applies to 816000-cm maps only; K=1 everywhere else.

    Skip it and every point drifts ~0.4% — 32 m at the edge of Erangel.
    """
    maps = {m["mapName"]: m for m in (await client.get("/api/maps")).json()}
    assert maps["Baltic_Main"]["worldSize"] == 816_000
    assert maps["Baltic_Main"]["imageScale"] == pytest.approx(8160 / 8192)
    assert maps["Range_Main"]["worldSize"] == 204_000
    assert maps["Range_Main"]["imageScale"] == 1.0


# ---------------------------------------------------------------------------
# players
# ---------------------------------------------------------------------------


async def test_player_list_and_search(client: httpx.AsyncClient) -> None:
    tracked = (await client.get("/api/players", params={"tracked": True})).json()
    assert tracked, "expected tracked players"
    assert all(p["tracked"] for p in tracked)

    name = tracked[0]["name"]
    hits = (await client.get("/api/players", params={"q": name.lower()})).json()
    assert any(p["name"] == name for p in hits), "search must be case-insensitive"


async def test_stats_report_both_kill_figures_honestly(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """`includeBots` chooses the headline; it must not change what a number means.

    Bots are ~19% of all kills and just over half of the tracked players', so a
    response where `kills` silently switched meaning would disagree with the
    match list without either looking wrong.
    """
    off = (await client.get(f"/api/players/{a_tracked_player}/stats")).json()
    on = (
        await client.get(
            f"/api/players/{a_tracked_player}/stats", params={"includeBots": "true"}
        )
    ).json()

    assert off["kills"] == on["kills"]
    assert off["killsHuman"] == on["killsHuman"]
    assert off["killsHuman"] <= off["kills"], "human kills cannot exceed total kills"
    assert off["includeBots"] is False
    assert on["includeBots"] is True, "the camelCase query alias must actually bind"


async def test_stats_derived_fields_are_consistent(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    s = (await client.get(f"/api/players/{a_tracked_player}/stats")).json()
    assert s["kd"] == pytest.approx(s["kills"] / s["matches"])
    assert s["kdHuman"] == pytest.approx(s["killsHuman"] / s["matches"])
    assert s["winRate"] == pytest.approx(s["wins"] / s["matches"])
    assert s["wins"] <= s["top10"] <= s["matches"]


async def test_unknown_player_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/players/account.nope/stats")).status_code == 404


async def test_player_matches_are_newest_first(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    rows = (
        await client.get(f"/api/players/{a_tracked_player}/matches", params={"limit": 10})
    ).json()
    assert rows
    played = [r["playedAt"] for r in rows]
    assert played == sorted(played, reverse=True)


async def test_weapons_exclude_the_distance_sentinel(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """`distance_cm = -1` means "not applicable" — 8.6% of kills carry it.

    Left in, it drags every average toward -1 and makes "longest kill"
    meaningless.
    """
    rows = (await client.get(f"/api/players/{a_tracked_player}/weapons")).json()
    for w in rows:
        assert w["longestM"] >= 0
        assert w["avgDistanceM"] >= 0
        assert w["headshots"] <= w["kills"]


# ---------------------------------------------------------------------------
# matches
# ---------------------------------------------------------------------------


async def test_match_detail_groups_by_roster(client: httpx.AsyncClient, a_match: str) -> None:
    """Participants carry no team id of their own — the roster is the only link."""
    m = (await client.get(f"/api/matches/{a_match}")).json()
    assert m["rosters"]
    ranks = [r["rank"] for r in m["rosters"]]
    assert ranks == sorted(ranks)
    assert sum(1 for r in m["rosters"] if r["won"]) <= 1

    everyone = [p for r in m["rosters"] for p in r["participants"]]
    assert everyone
    for r in m["rosters"]:
        for p in r["participants"]:
            assert p["teamId"] == r["teamId"]


async def test_match_detail_exposes_the_real_start_time(
    client: httpx.AsyncClient, a_match: str
) -> None:
    """`playedAt` is the API's *ingest* time; `telemetryT0` is the match start."""
    m = (await client.get(f"/api/matches/{a_match}")).json()
    assert m["parsed"] is True
    assert m["telemetryT0"] is not None


async def test_kill_feed_names_bots(client: httpx.AsyncClient, a_match: str) -> None:
    """Names come from `participants`, not `players`.

    Bots have no `players` row at all — their `ai.<n>` ids are match-scoped and
    recycled — so joining to `players` blanks every bot in the feed.
    """
    kills = (await client.get(f"/api/matches/{a_match}/kills")).json()
    if not kills:
        pytest.skip("match has no kills")
    assert all(k["victimName"] for k in kills), "every victim should resolve to a name"
    for k in kills:
        assert k["distanceM"] is None or k["distanceM"] > 0, "the -1 sentinel must not leak"


async def test_unknown_match_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/matches/nope/replay")).status_code == 404
    assert (await client.get("/api/matches/nope")).status_code == 404


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


async def test_replay_is_served_gzipped_and_immutable(
    client: httpx.AsyncClient, a_match: str
) -> None:
    """Served still-compressed, and cached forever.

    A bundle for a given parser_version never changes, and the version is in
    the object key, so a parser bump invalidates cleanly instead of needing a
    cache purge.
    """
    r = await client.get(f"/api/matches/{a_match}/replay", headers={"accept-encoding": "identity"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.msgpack"
    assert r.headers["content-encoding"] == "gzip"
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["x-parser-version"]


async def test_replay_bundle_decodes_with_intact_typed_arrays(
    client: httpx.AsyncClient, a_match: str
) -> None:
    """The renderer wraps these buffers directly; a length mismatch reads noise."""
    r = await client.get(f"/api/matches/{a_match}/replay")
    # httpx honours `Content-Encoding: gzip` and decodes transparently, exactly
    # as a browser does — so the body may already be plain MessagePack here.
    # Sniff the magic number rather than assuming either way.
    raw = r.content
    bundle = msgpack.unpackb(
        gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw,
        raw=False,
        strict_map_key=False,
    )

    n = bundle["pos"]["n"]
    assert len(bundle["pos"]["t"]) == n * 2  # Uint16
    assert len(bundle["pos"]["hp"]) == n  # Uint8
    assert len(bundle["pos"]["off"]) == (len(bundle["players"]) + 1) * 4
    assert bundle["le"] is True
    assert bundle["tickMs"] > 0
    # Server-side reparse bookkeeping must never reach the client — it was 23%
    # of the bundle when it lived inside.
    assert "heat" not in bundle


# ---------------------------------------------------------------------------
# heatmap
# ---------------------------------------------------------------------------


async def test_heatmap_decodes_to_a_dense_grid(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/heatmap", params={"map": "Baltic_Main", "kind": "movement"})
    assert r.status_code == 200
    body = r.json()

    cells = array("I")
    cells.frombytes(base64.b64decode(body["cells"]))
    assert len(cells) == body["grid"] ** 2
    assert sum(cells) == body["total"], "decoded grid must agree with the reported total"
    assert max(cells) == body["max"]


async def test_heatmap_all_players_is_a_superset_of_one(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """The `''` sentinel rows are the aggregate, and they are real values.

    If they were NULLs the upsert would never have fired and the global rows
    would be duplicated instead of summed.
    """
    everyone = (
        await client.get("/api/heatmap", params={"map": "Baltic_Main", "kind": "kill"})
    ).json()
    one = (
        await client.get(
            "/api/heatmap",
            params={"map": "Baltic_Main", "kind": "kill", "accountId": a_tracked_player},
        )
    ).json()
    assert one["total"] <= everyone["total"]
    assert one["total"] > 0


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------


async def test_ingest_status(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/ingest/status")).json()
    assert body["trackedPlayers"] >= 0
    assert body["rateLimitPerMin"] > 0
    assert isinstance(body["queue"], list)


async def test_backfill_unknown_player_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/ingest/backfill/account.nope")).status_code == 404
