"""Job-queue SQL primitives: enqueue / claim / complete / fail / reap.

Postgres `FOR UPDATE ... SKIP LOCKED` is the whole mechanism — no Redis, no
broker. Postgres' own wording for why that is safe here:

    "Skipping locked rows provides an inconsistent view of the data, so this is
    not suitable for general purpose work, but can be used to avoid lock
    contention with multiple consumers accessing a queue-like table."

Design decisions worth knowing before you edit anything:

* **Every helper commits.** The claim in particular *must* — it holds row locks
  taken by `FOR UPDATE SKIP LOCKED`, and a worker that kept that transaction open
  for the duration of a 19 MB telemetry parse would block autovacuum across the
  whole database. Job liveness after the commit is `locked_at` + the reaper's
  job, not the transaction's. :func:`enqueue` takes ``commit=False`` so an
  ingest transaction can persist a match and queue its follow-up work atomically.
* **`attempts` increments at claim, not at failure.** A worker killed with
  SIGKILL never reaches the failure path; counting at claim means a job that
  reliably crashes the process still dead-letters instead of poisoning the queue
  forever.
* **State strings, not an enum.** ``pending | running | done | failed`` per the
  model. Adding a value to a PG ENUM needs ``ALTER TYPE ... ADD VALUE``, which
  does not compose with Alembic's transactional migrations.
* Only ``pending``/``running`` rows participate in the dedupe index, so a match
  can legitimately be re-queued for parsing after a parser-version bump.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import Float, Integer, String, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import Job

STATE_PENDING: Final = "pending"
STATE_RUNNING: Final = "running"
STATE_DONE: Final = "done"
STATE_FAILED: Final = "failed"

#: Backoff ceiling. 2**attempts *minutes* grows past an hour at attempt 6, and a
#: PUBG outage is never usefully retried more often than hourly.
BACKOFF_CAP_SECONDS: Final = 3600.0

#: `last_error` is TEXT, but a full traceback in a queue row is a liability at
#: `SELECT *` time and in log shipping. Truncate at the SQL level.
_ERROR_MAX_CHARS: Final = 4000


class PermanentError(Exception):
    """Raised by a handler to say "this will never succeed — do not retry".

    Retrying a permanent failure is not merely wasteful here, it is *harmful*:
    the PUBG player endpoint allows 10 requests/minute, so five retries of a 404
    on a renamed account spend half a minute of budget to learn nothing. The
    client's own permanent errors (``PlayerNotFound``, ``TelemetryUnavailable``)
    should be re-raised as this, or caught by the handler and turned into one.
    """


def dedupe_key_for(kind: str, ident: str) -> str:
    """Build a dedupe key namespaced by kind.

    ``uq_jobs_dedupe_live`` is unique on ``dedupe_key`` **alone** — it does not
    include ``kind``. A bare match id as the key would therefore make
    ``fetch_telemetry`` and ``parse_telemetry`` for the same match mutually
    exclusive, and the second one would silently vanish. Always namespace.
    """
    return f"{kind}:{ident}"


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------
# Must match `uq_jobs_dedupe_live`'s predicate in db/models.py *character for
# character* — Postgres infers a partial unique index only when the ON CONFLICT
# predicate implies the index predicate. `ON CONFLICT ON CONSTRAINT` is not an
# option: the dedupe arbiter is a partial index, not a table constraint.
_DEDUPE_INDEX_WHERE = text("state IN ('pending', 'running')")


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any],
    dedupe_key: str,
    run_after: dt.datetime | None = None,
    max_attempts: int = 5,
    *,
    commit: bool = True,
) -> Job | None:
    """Queue one unit of work, or do nothing if it is already queued.

    Returns the new :class:`Job`, or ``None`` when an identical live job already
    existed. ``None`` is the *normal* outcome for a poller that re-sees the same
    match id every cycle — it is not an error.

    Args:
        dedupe_key: See :func:`dedupe_key_for`. Namespace it by kind.
        run_after: Earliest execution time. ``None`` means "as soon as a worker
            is free", pinned to the **database** clock rather than this process's
            — the claim predicate is ``run_after <= now()``, and mixing an app
            clock with the server clock produces jobs that are invisible for the
            length of the skew.
        commit: ``False`` to enlist in the caller's transaction, so match rows
            and the jobs that process them land atomically.
    """
    values: dict[str, Any] = {
        "kind": kind,
        "payload": payload,
        "dedupe_key": dedupe_key,
        "state": STATE_PENDING,
        "max_attempts": max_attempts,
        "run_after": run_after if run_after is not None else func.now(),
    }
    stmt = (
        pg_insert(Job)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[Job.dedupe_key],
            index_where=_DEDUPE_INDEX_WHERE,
        )
        .returning(Job.id)
    )
    job_id = (await session.execute(stmt)).scalar_one_or_none()
    if job_id is None:
        # DO NOTHING returns zero rows: a live job with this key already exists.
        if commit:
            await session.commit()
        return None

    job = await session.get(Job, job_id)
    if commit:
        await session.commit()
    return job


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------
# The subquery carries the locking clause because FOR UPDATE is a SELECT clause
# and cannot be attached to an UPDATE. LIMIT is applied *after* skipping, so a
# batch of n is filled with n genuinely-unlocked rows even under contention.
# ORDER BY run_after (and nothing else) is exactly `ix_jobs_claim`, whose partial
# predicate keeps the scan on the pending sliver no matter how many done rows
# have accumulated.
_CLAIM_SQL = text(
    """
    UPDATE jobs
       SET state = 'running',
           locked_at = now(),
           locked_by = :worker_id,
           attempts = attempts + 1
     WHERE id IN (
         SELECT id
           FROM jobs
          WHERE state = 'pending'
            AND run_after <= now()
            AND (:kinds IS NULL OR kind = ANY(:kinds))
          ORDER BY run_after
          LIMIT :limit
            FOR UPDATE SKIP LOCKED
     )
    RETURNING id
    """
).bindparams(
    # `kind = ANY(:array)` rather than `kind IN (...)`: one bind parameter and one
    # cached plan regardless of how many kinds this worker serves.
    bindparam("kinds", type_=ARRAY(String)),
    bindparam("limit", type_=Integer),
    bindparam("worker_id", type_=String),
)


async def claim(
    session: AsyncSession,
    kinds: Sequence[str] | None,
    worker_id: str,
    limit: int = 1,
) -> list[Job]:
    """Atomically take up to ``limit`` runnable jobs and mark them ``running``.

    Commits before returning so the row locks are released immediately; the
    returned jobs are detached but fully populated (the sessionmaker sets
    ``expire_on_commit=False``).

    Args:
        kinds: Restrict to these kinds. ``None`` or empty means *every* kind —
            an empty ``ARRAY[]`` would match nothing and the worker would idle
            forever without ever logging an error.
    """
    if limit <= 0:
        return []

    claimed_ids = list(
        (
            await session.scalars(
                _CLAIM_SQL,
                {
                    "kinds": list(kinds) if kinds else None,
                    "limit": limit,
                    "worker_id": worker_id,
                },
            )
        ).all()
    )
    if not claimed_ids:
        await session.commit()  # nothing locked, but do not leave a tx idle-in-transaction
        return []

    # Second round trip rather than `RETURNING *`: it loads real ORM instances
    # with every column populated, inside the same transaction as the claim.
    jobs = list(
        (
            await session.scalars(
                select(Job).where(Job.id.in_(claimed_ids)).order_by(Job.run_after, Job.id)
            )
        ).all()
    )
    await session.commit()
    # Detach so the caller can hand these to tasks that use other sessions.
    session.expunge_all()
    return jobs


# ---------------------------------------------------------------------------
# complete / fail / release
# ---------------------------------------------------------------------------
# `AND state = 'running'` on every transition: after a reap, a job can be running
# on a *second* worker while the first one — the one whose process hung — finally
# wakes up and tries to finish it. The guard makes that zombie write a no-op
# instead of overwriting the live worker's result.
_COMPLETE_SQL = text(
    """
    UPDATE jobs
       SET state = 'done',
           finished_at = now(),
           locked_at = NULL,
           locked_by = NULL,
           last_error = NULL
     WHERE id = :id AND state = 'running'
    RETURNING state
    """
).bindparams(bindparam("id", type_=Integer))

# Exponential backoff on the *database* clock: 2**attempts minutes, capped, plus
# up to 30s of jitter so a hundred jobs failed by one PUBG outage do not all come
# back in the same second. `attempts` was already incremented at claim, so
# attempts=1 -> ~2 min, 2 -> ~4 min, 3 -> ~8 min.
_FAIL_SQL = text(
    """
    UPDATE jobs
       SET state = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
           run_after = now() + make_interval(
               secs => least(power(2, attempts) * 60, :cap_s) + random() * 30
           ),
           last_error = left(:error, :error_max),
           locked_at = NULL,
           locked_by = NULL,
           finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END
     WHERE id = :id AND state = 'running'
    RETURNING state
    """
).bindparams(
    bindparam("id", type_=Integer),
    bindparam("error", type_=String),
    bindparam("error_max", type_=Integer),
    bindparam("cap_s", type_=Float),
)

_KILL_SQL = text(
    """
    UPDATE jobs
       SET state = 'failed',
           last_error = left(:error, :error_max),
           locked_at = NULL,
           locked_by = NULL,
           finished_at = now()
     WHERE id = :id AND state = 'running'
    RETURNING state
    """
).bindparams(
    bindparam("id", type_=Integer),
    bindparam("error", type_=String),
    bindparam("error_max", type_=Integer),
)

# Give the lease back without spending an attempt — used on graceful shutdown.
_RELEASE_SQL = text(
    """
    UPDATE jobs
       SET state = 'pending',
           run_after = now(),
           attempts = greatest(attempts - 1, 0),
           locked_at = NULL,
           locked_by = NULL,
           last_error = left(:error, :error_max)
     WHERE id = :id AND state = 'running'
    RETURNING state
    """
).bindparams(
    bindparam("id", type_=Integer),
    bindparam("error", type_=String),
    bindparam("error_max", type_=Integer),
)


async def complete(session: AsyncSession, job: Job) -> str | None:
    """Mark ``job`` done. Returns the new state, or ``None`` if it was not ours."""
    state = (await session.execute(_COMPLETE_SQL, {"id": job.id})).scalar_one_or_none()
    await session.commit()
    return state


async def fail(
    session: AsyncSession,
    job: Job,
    error: str,
    *,
    permanent: bool = False,
) -> str | None:
    """Record a failure and either schedule a retry or dead-letter the job.

    Returns ``"pending"`` (will retry), ``"failed"`` (dead-lettered), or ``None``
    if the job was no longer ``running`` — meaning it had been reaped and taken
    by someone else, so this result is stale and was correctly discarded.

    Args:
        permanent: Skip the retry schedule entirely. Use for
            :class:`PermanentError`: a 404 from PUBG is forever, and retrying it
            burns rate-limit budget five times to learn the same thing.
    """
    params: dict[str, Any] = {"id": job.id, "error": error, "error_max": _ERROR_MAX_CHARS}
    if permanent:
        state = (await session.execute(_KILL_SQL, params)).scalar_one_or_none()
    else:
        state = (
            await session.execute(_FAIL_SQL, params | {"cap_s": BACKOFF_CAP_SECONDS})
        ).scalar_one_or_none()
    await session.commit()
    return state


async def release(session: AsyncSession, job: Job, error: str = "released") -> str | None:
    """Return a still-good job to the queue without consuming an attempt.

    For shutdown, not for failure: a rolling restart must not push jobs closer to
    their ``max_attempts`` ceiling. ``attempts`` is decremented to undo the
    increment that :func:`claim` applied.
    """
    state = (
        await session.execute(
            _RELEASE_SQL, {"id": job.id, "error": error, "error_max": _ERROR_MAX_CHARS}
        )
    ).scalar_one_or_none()
    await session.commit()
    return state


# ---------------------------------------------------------------------------
# reap
# ---------------------------------------------------------------------------
# Without this a SIGKILLed worker leaves its jobs in 'running' forever and the
# pipeline wedges silently: nothing errors, nothing retries, telemetry just stops
# being ingested. The CASE is the second half of the guarantee — a job that
# crashes the *process* every time it runs would otherwise be reaped, re-claimed
# and re-crashed indefinitely, since the dead-letter check in fail() never runs
# for a process that dies. Attempts are counted at claim precisely so this works.
_REAP_SQL = text(
    """
    UPDATE jobs
       SET state = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
           run_after = now(),
           locked_at = NULL,
           locked_by = NULL,
           finished_at = CASE WHEN attempts >= max_attempts THEN now() ELSE NULL END,
           last_error = left(
               coalesce(last_error || ' | ', '')
               || 'reaped: lease expired, last held by ' || coalesce(locked_by, '?'),
               :error_max
           )
     WHERE state = 'running'
       AND (locked_at IS NULL OR locked_at < now() - make_interval(mins => :older_than_minutes))
    RETURNING id
    """
).bindparams(
    bindparam("older_than_minutes", type_=Integer),
    bindparam("error_max", type_=Integer),
)


async def reap_stale(session: AsyncSession, older_than_minutes: int = 30) -> int:
    """Recover jobs abandoned by a crashed worker. Returns how many were touched.

    ``older_than_minutes`` is a *lease*, so it must exceed the runtime of the
    slowest handler. Parsing a 19 MB / 35k-event telemetry file is the long pole
    here; 30 minutes is generous against that, and reaping a job that is merely
    slow means running it twice concurrently.
    """
    reaped = (
        await session.scalars(
            _REAP_SQL,
            {"older_than_minutes": older_than_minutes, "error_max": _ERROR_MAX_CHARS},
        )
    ).all()
    await session.commit()
    return len(reaped)
