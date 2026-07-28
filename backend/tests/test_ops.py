"""The watchdog, against a real Postgres.

Every check here guards a failure whose whole problem is that nobody notices
it. PUBG discards match history after ~14 days: a poller that stops is the one
fault in this system that re-running cannot fix, so the tests are about whether
the alarm actually rings, not about whether the query parses.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Base, Match, OpsAlert, Player, utcnow
from pubg_dashboard.ops.alerts import (
    beat,
    heartbeat_age_s,
    open_alerts,
    raise_alert,
    resolve_alert,
)
from pubg_dashboard.ops.doctor import WATCHDOG_NAME, run_checks
from pubg_dashboard.ops.retention import prune_telemetry
from pubg_dashboard.telemetry.bundle import PARSER_VERSION


def _scratch_dsn() -> str | None:
    override = os.environ.get("PUBGD_TEST_DATABASE_URL")
    if override:
        return override
    dsn = get_settings().database_url
    if not dsn:
        return None
    head, _, tail = dsn.rpartition("/")
    return f"{head}/pubg_test{'?' + tail.split('?', 1)[1] if '?' in tail else ''}"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    dsn = _scratch_dsn()
    if not dsn:
        pytest.skip("no database configured")
    engine = create_async_engine(dsn, poolclass=None)
    try:
        async with engine.begin() as conn:
            # Drop then create: `create_all` skips existing tables, so a schema
            # change between runs would otherwise be invisible.
            await conn.run_sync(Base.metadata.drop_all)
            # `create_all` reproduces the partial indexes, because they are
            # declared on the models rather than only in the migration.
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await engine.dispose()
        pytest.skip("scratch database unreachable")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _player(session: AsyncSession, name: str, *, polled_min_ago: float | None) -> None:
    session.add(
        Player(
            account_id=f"account.{name}",
            name=name,
            tracked=True,
            last_polled_at=(
                None
                if polled_min_ago is None
                else utcnow() - dt.timedelta(minutes=polled_min_ago)
            ),
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


async def test_repeated_alerts_update_one_row_rather_than_piling_up(
    session: AsyncSession,
) -> None:
    """A check runs every five minutes; a stall lasts hours.

    Without the partial unique index this would be one row per check, and the
    `ON CONFLICT` predicate has to spell `WHERE resolved_at IS NULL` exactly as
    the index does or Postgres cannot infer it — the same trap
    `uq_jobs_dedupe_live` documents.
    """
    await raise_alert(session, "poller_stalled", "first")
    await raise_alert(session, "poller_stalled", "second")
    await session.flush()

    rows = await open_alerts(session)
    assert len(rows) == 1
    assert rows[0].observations == 2
    # The newest observation wins: the detail should describe now, not an hour
    # ago, because that is what someone reading it is trying to act on.
    assert rows[0].detail == "second"


async def test_resolving_closes_the_row_and_a_recurrence_opens_a_new_one(
    session: AsyncSession,
) -> None:
    """Distinct incidents stay distinct.

    Resolution deletes nothing: two separate outages an hour apart are two
    facts about the week, and collapsing them loses the one that says this
    keeps happening.
    """
    await raise_alert(session, "queue_failed", "one")
    await resolve_alert(session, "queue_failed")
    await raise_alert(session, "queue_failed", "again")
    await session.flush()

    assert len(await open_alerts(session)) == 1
    total = await session.scalar(select(text("count(*)")).select_from(OpsAlert))
    assert total == 2


async def test_resolving_something_that_is_not_open_is_a_no_op(
    session: AsyncSession,
) -> None:
    await resolve_alert(session, "never_happened")
    assert await open_alerts(session) == []


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


async def test_a_tracked_player_who_has_never_been_polled_raises(
    session: AsyncSession,
) -> None:
    """The hole a lag calculation cannot see.

    `/health` computes `min(now() - last_polled_at)` filtered to
    `last_polled_at IS NOT NULL`, so a player who has never polled contributes
    nothing at all and the badge reads green off whoever is healthy. This is
    the single most likely way for the watchdog to ship broken.
    """
    await _player(session, "healthy", polled_min_ago=1)
    await _player(session, "ghost", polled_min_ago=None)
    await session.flush()

    findings = {f.kind: f for f in await run_checks(session)}
    assert not findings["player_never_polled"].ok
    assert "ghost" in findings["player_never_polled"].detail
    # And the lag check is *not* what caught it — that is the point.
    assert findings["poller_stalled"].ok


async def test_one_stale_player_raises_even_when_the_others_are_fresh(
    session: AsyncSession,
) -> None:
    """`min()` reports the freshest player; backoff reaches six hours.

    While everything works the batched poll makes min and max identical, which
    is exactly why the difference is invisible until it matters.
    """
    await _player(session, "fresh", polled_min_ago=1)
    await _player(session, "stuck", polled_min_ago=600)
    await session.flush()

    findings = {f.kind: f for f in await run_checks(session)}
    assert not findings["poller_stalled"].ok
    assert "600" in findings["poller_stalled"].detail or "10 h" in findings[
        "poller_stalled"
    ].detail.replace("600 min", "10 h")


async def test_a_healthy_system_raises_nothing_and_resolves_what_it_fixed(
    session: AsyncSession,
) -> None:
    await raise_alert(session, "poller_stalled", "stale from an earlier run")
    await _player(session, "fine", polled_min_ago=1)
    await session.flush()

    findings = await run_checks(session)
    assert all(f.ok for f in findings), [f for f in findings if not f.ok]
    assert await open_alerts(session) == []


async def test_the_watchdog_stamps_its_own_heartbeat(session: AsyncSession) -> None:
    """Something has to watch the watcher.

    A watchdog cannot report its own death, so it records that it ran and the
    API answers "it has not run in N minutes". `None` means it has never run,
    which is a reason to look rather than a missing value.
    """
    assert await heartbeat_age_s(session, WATCHDOG_NAME) is None

    await _player(session, "fine", polled_min_ago=1)
    await session.flush()
    await run_checks(session)
    await session.flush()

    age = await heartbeat_age_s(session, WATCHDOG_NAME)
    assert age is not None and age < 60

    await beat(session, WATCHDOG_NAME)
    await session.flush()
    assert (await heartbeat_age_s(session, WATCHDOG_NAME) or 999) < 5


async def test_telemetry_ageing_out_of_the_retention_window_raises(
    session: AsyncSession,
) -> None:
    """The check the whole module exists for.

    A match with no archived telemetry and a `played_at` approaching 14 days is
    about to become unreplayable forever. There is no recovery for this, only
    prevention, which is why it is an alert and not a log line.
    """
    session.add(
        Match(
            match_id="m-at-risk",
            shard="steam",
            map_name="Baltic_Main",
            game_mode="squad-fpp",
            match_type="official",
            duration_s=1800,
            played_at=utcnow() - dt.timedelta(days=12),
            telemetry_key=None,
        )
    )
    await _player(session, "fine", polled_min_ago=1)
    await session.flush()

    findings = {f.kind: f for f in await run_checks(session)}
    assert not findings["telemetry_at_risk"].ok
    assert "12 days" in findings["telemetry_at_risk"].detail


# ---------------------------------------------------------------------------
# retention
# ---------------------------------------------------------------------------


async def _match(
    session: AsyncSession, match_id: str, *, days_old: int, parser_version: int | None
) -> None:
    session.add(
        Match(
            match_id=match_id,
            shard="steam",
            map_name="Baltic_Main",
            game_mode="squad-fpp",
            match_type="official",
            duration_s=1800,
            played_at=utcnow() - dt.timedelta(days=days_old),
            telemetry_key=f"telemetry/{match_id}.json.gz",
            telemetry_parsed_at=None if parser_version is None else utcnow(),
            parser_version=parser_version,
        )
    )
    await session.flush()


async def test_prune_never_touches_a_match_below_the_head_parser_version(
    session: AsyncSession,
) -> None:
    """The guard that stops a prune from silently deleting heatmap data.

    A match at an older parser version is going to be reparsed by the next
    bump. Prune its telemetry and the reparse produces nothing while the heat
    ledger is still subtracted — its contribution vanishes from the heatmap and
    nothing errors. This project has spent four parser bumps in a single
    session, so it is not a hypothetical.
    """
    await _match(session, "current", days_old=400, parser_version=PARSER_VERSION)
    await _match(session, "stale-parse", days_old=400, parser_version=PARSER_VERSION - 1)
    await _match(session, "never-parsed", days_old=400, parser_version=None)

    ids = {c.match_id for c in await prune_telemetry(session, 30)}
    assert ids == {"current"}


async def test_prune_is_disabled_by_default(session: AsyncSession) -> None:
    """0 days means off, and off is the default.

    Raw telemetry is what makes `PARSER_VERSION` re-derivable. Expiring it buys
    disk and sells the ability to fix the past.
    """
    await _match(session, "ancient", days_old=9999, parser_version=PARSER_VERSION)
    assert await prune_telemetry(session, 0) == []
    assert await prune_telemetry(session, -1) == []
