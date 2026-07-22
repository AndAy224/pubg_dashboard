"""Job-queue behaviour against a **real** Postgres.

These cannot be unit tests. Every property that matters here is a property of
Postgres itself, not of our Python:

* `ON CONFLICT DO NOTHING` only suppresses a duplicate if Postgres can *infer*
  the partial unique index, which depends on the statement's predicate proving
  the index's predicate. A mock cannot tell you whether that inference happened
  — and when it silently does not, the poller re-enqueues every match it sees
  on every cycle, forever.
* `FOR UPDATE SKIP LOCKED` is the entire concurrency story for the worker pool.
* Partial-index predicates (`state IN ('pending','running')`) are normalised by
  Postgres to `state = ANY(ARRAY[...])`. That the two still match is a fact
  about the planner, verified here rather than assumed.

`tests/conftest.py` is deliberately Postgres-free, so the fixture lives in this
module. With no database reachable the whole file skips, keeping a source-only
checkout green.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Base, Job
from pubg_dashboard.ingest import queue as ingest_queue
from pubg_dashboard.queue import jobs as q


def _test_dsn() -> str:
    """The configured DSN, redirected at a scratch database.

    Never the real one: these tests TRUNCATE between cases.
    """
    dsn = os.environ.get("PUBGD_TEST_DATABASE_URL")
    if dsn:
        return dsn
    base = get_settings().database_url
    head, _, tail = base.partition("?")
    return f"{head.rsplit('/', 1)[0]}/pubg_test" + (f"?{tail}" if tail else "")


# Function-scoped on purpose. `asyncio_mode = auto` gives every test its own
# event loop, and an async fixture of a wider scope would hand tests an engine
# bound to a loop that is already closed ("another operation is in progress").
@pytest_asyncio.fixture
async def engine() -> AsyncIterator[object]:
    eng = create_async_engine(_test_dsn())
    try:
        async with eng.begin() as conn:
            # create_all reproduces the partial indexes too — they are declared
            # in models.py __table_args__ with `postgresql_where`, which is the
            # same definition 0001_initial.py installs by hand.
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await eng.dispose()
        pytest.skip(f"no Postgres at {_test_dsn()}: {exc}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: object) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)  # type: ignore[arg-type]
    async with maker() as s:
        await s.execute(sql("TRUNCATE jobs"))
        await s.commit()
        yield s


# ---------------------------------------------------------------------------
# enqueue / dedupe
# ---------------------------------------------------------------------------
async def test_duplicate_live_job_is_suppressed(session: AsyncSession) -> None:
    key = q.dedupe_key_for("fetch_match", "M1")
    assert await q.enqueue(session, "fetch_match", {"match_id": "M1"}, key) is not None
    # The whole idempotency story: a poller re-seeing the same match must not
    # queue a second download.
    assert await q.enqueue(session, "fetch_match", {"match_id": "M1"}, key) is None


async def test_different_kinds_for_one_match_coexist(session: AsyncSession) -> None:
    """`uq_jobs_dedupe_live` is unique on `dedupe_key` alone, not (kind, key).

    Namespacing the key by kind is what keeps `fetch_telemetry` and
    `parse_telemetry` for the same match from evicting one another.
    """
    for kind in ("fetch_match", "fetch_telemetry", "parse_telemetry"):
        got = await q.enqueue(session, kind, {"match_id": "M1"}, q.dedupe_key_for(kind, "M1"))
        assert got is not None, f"{kind} was wrongly deduped against another kind"


async def test_finished_job_may_be_requeued(session: AsyncSession) -> None:
    """The dedupe index covers *live* rows only — that is what makes reparse work."""
    key = q.dedupe_key_for("parse_telemetry", "M1")
    assert await q.enqueue(session, "parse_telemetry", {"match_id": "M1"}, key) is not None
    await session.execute(sql("UPDATE jobs SET state='done'"))
    await session.commit()
    assert await q.enqueue(session, "parse_telemetry", {"match_id": "M1"}, key) is not None


async def test_bulk_enqueue_dedupes_within_and_across_statements(
    session: AsyncSession,
) -> None:
    # A duplicate *inside one INSERT* — teammates share match ids, and the
    # poller batches them.
    assert await ingest_queue.enqueue_match_fetches(session, ["M2", "M3", "M2"]) == 2
    await session.commit()
    assert await ingest_queue.enqueue_match_fetches(session, ["M2", "M3"]) == 0


# ---------------------------------------------------------------------------
# claim / complete / fail / reap
# ---------------------------------------------------------------------------
async def test_claim_is_exclusive_and_counts_the_attempt(session: AsyncSession) -> None:
    for i in range(3):
        await q.enqueue(session, "fetch_match", {"m": i}, q.dedupe_key_for("fetch_match", str(i)))

    first = await q.claim(session, None, "w1", limit=2)
    assert len(first) == 2
    # Incremented at claim, not at failure: a worker killed with SIGKILL never
    # reaches the failure path, and a job that reliably crashes the process must
    # still dead-letter instead of poisoning the queue forever.
    assert [j.attempts for j in first] == [1, 1]

    # A second worker must never be handed a row the first one holds.
    assert len(await q.claim(session, None, "w2", limit=5)) == 1
    assert await q.claim(session, None, "w3", limit=5) == []


async def test_claim_kind_filter(session: AsyncSession) -> None:
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    assert await q.claim(session, ["parse_telemetry"], "w1", limit=5) == []
    assert len(await q.claim(session, ["fetch_match"], "w1", limit=5)) == 1


async def test_claim_with_no_kinds_means_every_kind(session: AsyncSession) -> None:
    """`None` must not degrade to `ARRAY[]`, which matches nothing.

    A worker that silently idles forever looks identical to an empty queue.
    """
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    assert len(await q.claim(session, None, "w1", limit=5)) == 1


async def test_fail_retries_then_dead_letters(session: AsyncSession) -> None:
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    (job,) = await q.claim(session, None, "w1", limit=1)
    assert await q.fail(session, job, "boom") == q.STATE_PENDING

    await session.execute(sql("UPDATE jobs SET attempts = max_attempts, state='running'"))
    await session.commit()
    job = await session.get(Job, job.id)
    assert job is not None
    assert await q.fail(session, job, "boom") == q.STATE_FAILED


async def test_permanent_failure_skips_the_retry_budget(session: AsyncSession) -> None:
    """404 from PUBG is terminal — the match aged out of the 14-day window.

    Burning five retries on it spends rate-limit budget to learn nothing.
    """
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    (job,) = await q.claim(session, None, "w1", limit=1)
    assert await q.fail(session, job, "gone", permanent=True) == q.STATE_FAILED


async def test_reaper_requeues_jobs_whose_worker_died(session: AsyncSession) -> None:
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    await q.claim(session, None, "w1", limit=1)
    # The worker was SIGKILLed: state is still `running` and the lock is stale.
    await session.execute(sql("UPDATE jobs SET locked_at = now() - interval '2 hours'"))
    await session.commit()

    assert await q.reap_stale(session, older_than_minutes=30) == 1
    assert await session.scalar(sql("SELECT state FROM jobs")) == q.STATE_PENDING


async def test_reaper_leaves_live_workers_alone(session: AsyncSession) -> None:
    await q.enqueue(session, "fetch_match", {}, q.dedupe_key_for("fetch_match", "M1"))
    await q.claim(session, None, "w1", limit=1)
    assert await q.reap_stale(session, older_than_minutes=30) == 0
