"""API surface, exercised against the real ingested archive.

These run through `httpx.ASGITransport` — no socket, no uvicorn — but against
the live Postgres and object storage, because the interesting failures are in
the queries and the serialisation, not in the routing.
"""

from __future__ import annotations

import base64
import gzip
import re
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


# ---------------------------------------------------------------------------
# tiles
# ---------------------------------------------------------------------------


async def test_tile_manifest_derives_px_per_metre(client: httpx.AsyncClient) -> None:
    """Same 8192px source, 4x different scale — it has to be derived."""
    r = await client.get("/api/tiles/manifest.json")
    if r.status_code == 404:
        pytest.skip("no tiles built")
    data = r.json()
    assert data["Baltic_Main"]["pxPerMetre"] == pytest.approx(1.0)
    if "Range_Main" in data:
        assert data["Range_Main"]["pxPerMetre"] == pytest.approx(4.0, rel=0.01)
    assert "{z}" in data["Baltic_Main"]["tileUrl"]


async def test_tiles_are_served_immutable(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/tiles/Baltic_Main/0/0_0.webp")
    if r.status_code == 404:
        pytest.skip("no tiles built")
    assert r.headers["content-type"] == "image/webp"
    assert "immutable" in r.headers["cache-control"]
    assert r.content[:4] == b"RIFF"


@pytest.mark.parametrize(
    "path",
    ["Baltic_Main/0/0_0.png", "Baltic_Main/0/notanint_0.webp", "Baltic_Main/0/1_1_1.webp"],
)
async def test_malformed_tile_requests_are_404(client: httpx.AsyncClient, path: str) -> None:
    """Components are validated rather than joined blindly."""
    assert (await client.get(f"/api/tiles/{path}")).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/tiles/Baltic_Main/0/../../../../../../etc/passwd",
        "/api/tiles/../../../../../../etc/passwd",
        "/api/tiles/Baltic_Main/0/..%2f..%2f..%2f..%2f..%2f..%2fetc%2fpasswd",
    ],
)
async def test_tile_traversal_never_leaks_a_file(client: httpx.AsyncClient, path: str) -> None:
    """The property is "no file escapes", not a particular status code.

    Some of these normalise out of /api entirely before routing and land on
    the SPA shell, which is a 200 — so asserting 404 would be testing the
    router's shape rather than the thing that matters.
    """
    r = await client.get(path)
    assert "root:x:0:0" not in r.text
    assert r.headers.get("content-type") != "image/webp"


# ---------------------------------------------------------------------------
# static SPA
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../../../../../etc/passwd",
        "..%2f..%2f..%2f..%2f..%2fetc%2fpasswd",
        "../../../../../../home/pubg/pubg_dashboard/.env",
        "assets/../../../../../etc/passwd",
    ],
)
async def test_spa_never_serves_files_outside_the_build(
    client: httpx.AsyncClient, path: str
) -> None:
    """This was a real vulnerability, not a hypothetical.

    Starlette decodes `%2e%2e%2f` before the handler sees it, so `dist / path`
    resolved outside the build directory. Before the containment check,
    `GET /..%2f..%2f..%2f..%2f..%2fetc%2fpasswd` returned the real /etc/passwd.
    An escaping path must fall through to the SPA shell.
    """
    r = await client.get(f"/{path}")
    assert r.status_code == 200
    assert "root:x:0:0" not in r.text
    assert "PUBG_API_KEY" not in r.text


async def test_spa_serves_client_routes(client: httpx.AsyncClient) -> None:
    """Only the browser knows /matches/<id>/replay is a route, so it gets the shell."""
    r = await client.get("/matches/whatever/replay")
    if r.status_code == 404:
        pytest.skip("frontend not built")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


async def test_the_shell_must_revalidate_and_assets_must_not(
    client: httpx.AsyncClient,
) -> None:
    """A deploy nobody receives looks exactly like a feature never written.

    `FileResponse` sets no `Cache-Control`, so the shell carried no freshness
    information at all and browsers fell back to inventing a lifetime from
    `Last-Modified`. A shell served from that heuristic names the *previous*
    build's chunk hashes, and if those are cached too the whole stale app boots
    happily — the page works, it is simply the old one. That is how a feature
    verified rendering on the server can be invisible in an already-open tab.

    The fingerprinted assets want the opposite: their names are content hashes,
    so revalidating them on every navigation is pure round trips.
    """
    shell = await client.get("/matches/whatever/replay")
    if shell.status_code == 404:
        pytest.skip("frontend not built")
    assert shell.headers.get("cache-control") == "no-cache"

    index = await client.get("/")
    asset = re.search(r'assets/[A-Za-z0-9_.-]+\.js', index.text)
    assert asset, "the shell should reference at least one hashed asset"
    r = await client.get(f"/{asset.group(0)}")
    assert r.status_code == 200
    assert "immutable" in r.headers.get("cache-control", "")


async def test_api_routes_are_not_shadowed_by_the_spa(client: httpx.AsyncClient) -> None:
    """The catch-all is mounted after every router; /api must still be JSON."""
    r = await client.get("/api/health")
    assert r.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# The enriched match feed
# ---------------------------------------------------------------------------
async def test_feed_says_who_played_and_where_they_finished(
    client: httpx.AsyncClient,
) -> None:
    """The whole point of the feed rewrite.

    A row that lists only map, mode and duration describes a match nobody can
    identify. Every tracked-only row must carry a placement and at least one
    named result.
    """
    r = await client.get("/api/matches?limit=10")
    assert r.status_code == 200
    rows = r.json()
    if not rows:
        pytest.skip("no matches ingested")

    for row in rows:
        assert row["results"], f"{row['matchId']} has no tracked results"
        assert row["winPlace"] is not None
        for result in row["results"]:
            assert result["name"]
            assert result["winPlace"] == row["winPlace"], (
                "tracked players share a roster, so their placement must match "
                "the row's — a disagreement means the roster join broke"
            )


async def test_feed_placement_and_kills_match_the_database(
    client: httpx.AsyncClient,
) -> None:
    """Cross-check the feed against the tables it summarises."""
    from pubg_dashboard.db.models import Participant

    r = await client.get("/api/matches?limit=5")
    rows = r.json()
    if not rows:
        pytest.skip("no matches ingested")

    async with get_session() as session:
        for row in rows:
            for result in row["results"]:
                p = (
                    await session.execute(
                        select(Participant).where(
                            Participant.match_id == row["matchId"],
                            Participant.account_id == result["accountId"],
                        )
                    )
                ).scalar_one()
                assert result["winPlace"] == p.win_place
                assert result["kills"] == p.kills
                assert result["killsHuman"] == p.kills_human


async def test_feed_limit_counts_matches_not_participants(
    client: httpx.AsyncClient,
) -> None:
    """The reason the feed is two statements rather than one join.

    Joining tracked participants before LIMIT would multiply each match by the
    number of tracked players in it, so a page of 5 would return 2 matches on
    a night all three of them squadded.
    """
    r = await client.get("/api/matches?limit=5")
    rows = r.json()
    if len(rows) < 5:
        pytest.skip("fewer than 5 matches ingested")
    assert len(rows) == 5
    assert len({row["matchId"] for row in rows}) == 5


async def test_feed_keyset_pagination_does_not_repeat_rows(
    client: httpx.AsyncClient,
) -> None:
    first = (await client.get("/api/matches?limit=3")).json()
    if len(first) < 3:
        pytest.skip("not enough matches")
    cursor = first[-1]["playedAt"]
    second = (await client.get(f"/api/matches?limit=3&before={cursor}")).json()
    assert not ({r["matchId"] for r in first} & {r["matchId"] for r in second})


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
async def test_overview_is_one_request_for_the_whole_home_page(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert {"players", "matches", "health", "session"} <= set(body)
    assert body["health"]["matches"] >= 0
    for p in body["players"]:
        assert p["card"]["tracked"]
        # `stats` may legitimately be null (no official matches), but the form
        # strip must still be a list rather than missing.
        assert isinstance(p["form"], list)


async def test_overview_form_is_oldest_first(client: httpx.AsyncClient) -> None:
    """The strip reads left to right, so the array must too."""
    body = (await client.get("/api/overview")).json()
    for p in body["players"]:
        days = [f["playedAt"] for f in p["form"]]
        assert days == sorted(days), f"{p['card']['name']} form is not chronological"


async def test_overview_session_covers_a_contiguous_run(
    client: httpx.AsyncClient,
) -> None:
    from pubg_dashboard.api.routers.players import SESSION_GAP_S

    body = (await client.get("/api/overview")).json()
    session = body["session"]
    if session is None:
        pytest.skip("no matches")
    assert session["matches"] >= 1
    assert session["startedAt"] <= session["endedAt"]
    assert session["spanS"] >= 0
    # A session must not span more than its own matches plus the permitted gaps.
    assert session["spanS"] <= session["matches"] * (SESSION_GAP_S + 3600)


# ---------------------------------------------------------------------------
# Stats that the corpus can check
# ---------------------------------------------------------------------------
async def test_accuracy_is_absent_rather_than_zero(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """`shotsFired == 0` means PUBG did not report, not "fired nothing".

    PUBG populates `allWeaponStats` for ~2 accounts per match, so this is the
    normal case. What must never happen is a non-zero accuracy on zero shots,
    which would be a fabricated statistic.
    """
    s = (await client.get(f"/api/players/{a_tracked_player}/stats")).json()
    assert s["shotsFired"] >= 0
    assert s["shotsHit"] <= s["shotsFired"] or s["shotsFired"] == 0
    if s["shotsFired"] == 0:
        assert s["accuracy"] == 0.0
    else:
        assert 0.0 < s["accuracy"] <= 1.0


async def test_headshot_rate_uses_raw_kills_on_both_sides(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """`headshot_kills` is the API's figure and counts bots, so dividing it by
    `kills_human` would report rates above 100%."""
    s = (await client.get(f"/api/players/{a_tracked_player}/stats")).json()
    assert 0.0 <= s["headshotRate"] <= 1.0
    if s["kills"]:
        assert s["headshotRate"] == pytest.approx(s["headshotKills"] / s["kills"])


async def test_placements_cover_every_career_match(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """The buckets partition the range, so they must sum to the match count."""
    stats = (await client.get(f"/api/players/{a_tracked_player}/stats")).json()
    buckets = (await client.get(f"/api/players/{a_tracked_player}/placements")).json()
    assert sum(b["matches"] for b in buckets) == stats["matches"]


async def test_nemeses_exclude_bots_and_self(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """Bot ids are recycled — `ai.322` alone is 14 unrelated bots — so
    grouping kills by one would invent a single arch-enemy."""
    rows = (await client.get(f"/api/players/{a_tracked_player}/nemeses")).json()
    for n in rows:
        assert n["accountId"].startswith("account."), f"bot leaked in: {n}"
        assert n["accountId"] != a_tracked_player
        assert n["killedBy"] > 0 or n["killed"] > 0


# ---------------------------------------------------------------------------
# Heatmap match_type dimension
# ---------------------------------------------------------------------------
async def test_heatmap_official_agrees_with_kill_events(
    client: httpx.AsyncClient, a_tracked_player: str
) -> None:
    """The reason `match_type` joined the primary key.

    Binned kills for one player, filtered to `official`, must equal that
    player's official kill_events rows exactly. Before the dimension existed
    the heatmap silently included airoyale and tutorial matches while career
    stats did not.
    """
    from pubg_dashboard.db.models import KillEvent

    r = await client.get(
        f"/api/heatmap?map=Baltic_Main&kind=kill&accountId={a_tracked_player}"
        "&matchType=official"
    )
    assert r.status_code == 200
    binned = r.json()["total"]

    async with get_session() as session:
        expected = await session.scalar(
            select(func.count())
            .select_from(KillEvent)
            .join(Match, Match.match_id == KillEvent.match_id)
            .where(
                KillEvent.killer_account_id == a_tracked_player,
                Match.match_type == "official",
                Match.map_name == "Baltic_Main",
            )
        )
    assert binned == expected


async def test_heatmap_all_types_is_a_superset_of_official(
    client: httpx.AsyncClient,
) -> None:
    """`all` is a sentinel, not an empty string: a client that drops empty
    query parameters would otherwise silently get `official` back while
    believing it asked for everything."""
    official = (await client.get("/api/heatmap?kind=kill&matchType=official")).json()
    every = (await client.get("/api/heatmap?kind=kill&matchType=all")).json()
    assert every["total"] >= official["total"]


async def test_heatmap_is_compressed(client: httpx.AsyncClient) -> None:
    """A dense 256x256 Uint32 grid is ~350 KB of mostly-zero base64."""
    r = await client.get(
        "/api/heatmap?kind=movement&matchType=all", headers={"accept-encoding": "gzip"}
    )
    assert r.status_code == 200
    # httpx transparently decodes, so check the header rather than the size.
    assert r.headers.get("content-encoding") == "gzip"


async def test_replay_bundle_is_not_double_compressed(
    client: httpx.AsyncClient, a_match: str
) -> None:
    """The bundle is served still-gzipped from object storage. GZipMiddleware
    must skip it rather than re-compressing an already-compressed body.

    httpx, like a browser, transparently decodes one layer of
    `Content-Encoding`, so `r.content` should already be MessagePack. Had the
    middleware compressed it a second time, one layer of gzip would remain and
    `unpackb` would fail on the gzip magic instead.
    """
    r = await client.get(f"/api/matches/{a_match}/replay")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    bundle = msgpack.unpackb(r.content, raw=False)
    assert bundle["matchId"] == a_match
