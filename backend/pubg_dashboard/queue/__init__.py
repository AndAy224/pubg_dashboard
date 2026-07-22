"""Postgres-backed job queue.

`pubg_dashboard.queue` deliberately shadows nothing: absolute imports of the
stdlib ``queue`` module elsewhere in the package still resolve to the stdlib,
because Python 3 has no implicit relative imports.

Public surface lives in :mod:`pubg_dashboard.queue.jobs` (SQL primitives) and
:mod:`pubg_dashboard.queue.worker` (the loop + the handler registry).
"""

from __future__ import annotations

from pubg_dashboard.queue.jobs import (
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    PermanentError,
    claim,
    complete,
    dedupe_key_for,
    enqueue,
    fail,
    reap_stale,
    release,
)

__all__ = [
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_PENDING",
    "STATE_RUNNING",
    "PermanentError",
    "claim",
    "complete",
    "dedupe_key_for",
    "enqueue",
    "fail",
    "reap_stale",
    "release",
]
