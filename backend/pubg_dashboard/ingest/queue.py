"""Idempotent enqueueing onto the Postgres job table.

Only the *write* half of the queue lives here — claiming, retrying and reaping
belong to the worker. These helpers deliberately do NOT commit: a job is
enqueued inside the same transaction as the rows that justify it, so we can
never end up with telemetry work queued for a match that was rolled back, nor a
match ingested with no follow-up job.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import Job, utcnow

JOB_FETCH_MATCH: Final = "fetch_match"
JOB_FETCH_TELEMETRY: Final = "fetch_telemetry"
JOB_PARSE_TELEMETRY: Final = "parse_telemetry"
JOB_BACKFILL_PLAYER: Final = "backfill_player"

# Postgres caps a statement at 65535 bind parameters (Int16 in the Bind
# message). 8 columns per job row leaves plenty of head-room at 1000 rows.
_CHUNK_ROWS: Final = 1000


def dedupe_key(kind: str, ident: str) -> str:
    """Stable key for one logical unit of work.

    `uq_jobs_dedupe_live` is unique over *live* jobs only (pending|running), so
    the same key may be re-enqueued once the previous job finished — which is
    what makes a re-parse after a parser upgrade possible.
    """
    return f"{kind}:{ident}"


def _job_row(
    kind: str,
    payload: Mapping[str, Any],
    *,
    key: str,
    max_attempts: int,
    run_after: dt.datetime | None,
    now: dt.datetime,
) -> dict[str, Any]:
    # Every row carries every column: a multi-VALUES insert derives its column
    # list from the first dict, and `run_after`/`created_at` have Python-side
    # (not server-side) defaults that a bulk insert would not fill in.
    return {
        "kind": kind,
        "payload": dict(payload),
        "dedupe_key": key,
        "state": "pending",
        "attempts": 0,
        "max_attempts": max_attempts,
        "run_after": run_after or now,
        "created_at": now,
    }


async def enqueue_many(
    session: AsyncSession,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    """Insert pre-built job rows, skipping any that already have a live twin.

    Returns the number of jobs actually created (deduped ones are not counted).
    """
    if not rows:
        return 0

    created = 0
    for start in range(0, len(rows), _CHUNK_ROWS):
        chunk = [dict(row) for row in rows[start : start + _CHUNK_ROWS]]
        stmt = pg_insert(Job).values(chunk)
        # No conflict target: `uq_jobs_dedupe_live` is a *partial* unique index
        # and a bare DO NOTHING covers every constraint on the table, which is
        # exactly the semantics we want (two pollers racing on the same match
        # produce one job).
        stmt = stmt.on_conflict_do_nothing().returning(Job.id)
        result = await session.execute(stmt)
        created += len(result.fetchall())
    return created


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: Mapping[str, Any],
    *,
    key: str | None = None,
    max_attempts: int = 5,
    run_after: dt.datetime | None = None,
) -> bool:
    """Enqueue a single job. Returns False when it was deduplicated away."""
    now = utcnow()
    ident = key or str(next(iter(payload.values()), kind))
    row = _job_row(
        kind,
        payload,
        key=dedupe_key(kind, ident),
        max_attempts=max_attempts,
        run_after=run_after,
        now=now,
    )
    return await enqueue_many(session, [row]) == 1


async def enqueue_match_fetches(
    session: AsyncSession,
    match_ids: Iterable[str],
    *,
    max_attempts: int = 5,
) -> int:
    """Queue `fetch_match` for many ids in one statement."""
    now = utcnow()
    # Ordered dedupe: teammates in the same batch share match ids, and two
    # identical dedupe_keys in one INSERT would abort the whole statement.
    unique = list(dict.fromkeys(match_ids))
    rows = [
        _job_row(
            JOB_FETCH_MATCH,
            {"match_id": match_id},
            key=dedupe_key(JOB_FETCH_MATCH, match_id),
            max_attempts=max_attempts,
            run_after=None,
            now=now,
        )
        for match_id in unique
    ]
    return await enqueue_many(session, rows)
