"""Generic async job worker: claim -> dispatch -> complete/fail.

The worker knows nothing about PUBG. Feature modules register coroutines against
a job ``kind`` and the loop does the rest::

    from pubg_dashboard.queue.worker import register

    @register("fetch_telemetry")
    async def fetch_telemetry(job: Job) -> None:
        ...

Shape of the loop, and why:

* **Claim only as many jobs as there are free slots.** A claimed job is locked
  out of every other worker's reach; over-claiming parks work in one process
  while its siblings idle.
* **Every handler opens its own session.** An ``AsyncSession`` is not safe across
  concurrent tasks, and the loop's own session is committed and closed the moment
  the claim returns.
* **The loop never dies.** A handler exception fails one job; a claim failure
  (database restart, failover) backs off and retries. Only a signal stops it.
* **Graceful shutdown drains.** SIGINT/SIGTERM stop new claims and wait out the
  in-flight jobs. Anything still running when the grace period expires is
  cancelled and its lease *released* — returned to the queue without spending an
  attempt, so a rolling deploy cannot dead-letter healthy work.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib
import os
import signal
import socket
from collections.abc import Awaitable, Callable, Sequence
from typing import Final

import structlog

from pubg_dashboard.db.models import Job
from pubg_dashboard.db.session import dispose_engine, get_session
from pubg_dashboard.queue import jobs as q

log = structlog.get_logger(__name__)

#: Written to `jobs.locked_by`. The first question in any incident is "which box
#: and which process is sitting on this job", so encode both.
WORKER_ID: Final = f"{socket.gethostname()}:{os.getpid()}"

Handler = Callable[[Job], Awaitable[None]]

#: kind -> coroutine. Populated by feature modules at import time.
HANDLERS: dict[str, Handler] = {}

#: Modules imported by :func:`main` purely for their registration side effects.
#: Missing ones are a warning, not a crash — the worker is useful with a subset.
HANDLER_MODULES: tuple[str, ...] = ("pubg_dashboard.pipeline.handlers",)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def register(kind: str) -> Callable[[Handler], Handler]:
    """Decorator form: ``@register("fetch_match")``."""

    def decorate(handler: Handler) -> Handler:
        register_handler(kind, handler)
        return handler

    return decorate


def register_handler(kind: str, handler: Handler) -> None:
    existing = HANDLERS.get(kind)
    # Silently overwriting means whichever module imported last wins, which is
    # import-order-dependent and impossible to debug from the outside.
    if existing is not None and existing is not handler:
        raise ValueError(f"kind {kind!r} already handled by {existing!r}")
    HANDLERS[kind] = handler


def load_handler_modules(modules: Sequence[str] = HANDLER_MODULES) -> None:
    for name in modules:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # Only swallow "this module does not exist". A missing *dependency*
            # inside a module that does exist is a real bug and must surface.
            if exc.name != name:
                raise
            log.warning("worker.handler_module_missing", module=name)


# ---------------------------------------------------------------------------
# loop
# ---------------------------------------------------------------------------
async def _wait_or_stop(stop: asyncio.Event, timeout: float) -> None:
    """Sleep, but wake instantly when shutdown is requested."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            # Windows' ProactorEventLoop has no add_signal_handler. The C-level
            # handler only runs between bytecodes, i.e. when the loop next wakes
            # — which the poll/reap sleeps guarantee within a second or so.
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _run_one(job: Job, registry: dict[str, Handler]) -> None:
    logger = log.bind(job_id=job.id, kind=job.kind, attempt=job.attempts)

    handler = registry.get(job.kind)
    if handler is None:
        # Permanent by construction: no amount of retrying invents a handler.
        async with get_session() as session:
            await q.fail(
                session, job, f"no handler registered for kind={job.kind!r}", permanent=True
            )
        logger.error("job.no_handler")
        return

    try:
        await handler(job)
    except asyncio.CancelledError:
        # Shutdown deadline. Best effort: hand the lease back so a sibling picks
        # it up now instead of after the reaper's lease window. The reaper is the
        # backstop if this write does not make it out.
        with contextlib.suppress(Exception):
            async with get_session() as session:
                await q.release(session, job, "worker shutting down")
        logger.warning("job.cancelled")
        raise
    except q.PermanentError as exc:
        async with get_session() as session:
            await q.fail(session, job, repr(exc), permanent=True)
        logger.warning("job.dead_lettered", error=str(exc))
    except Exception as exc:  # one bad job must not stop the worker
        async with get_session() as session:
            state = await q.fail(session, job, repr(exc))
        logger.exception("job.failed", next_state=state)
    else:
        async with get_session() as session:
            await q.complete(session, job)
        logger.info("job.done")


def _job_task_done(inflight: set[asyncio.Task[None]], task: asyncio.Task[None]) -> None:
    inflight.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        # _run_one records job failures itself, so anything escaping it is a bug
        # in the worker (or in the logger). Retrieving it here is what stops
        # asyncio reporting "Task exception was never retrieved" at GC time,
        # minutes later and with no job context attached.
        log.error("worker.job_task_crashed", task=task.get_name(), exc_info=exc)


async def _reap_loop(stop: asyncio.Event, interval_s: float, stale_after_minutes: int) -> None:
    """Periodically un-wedge jobs left ``running`` by a crashed worker."""
    while not stop.is_set():
        try:
            async with get_session() as session:
                reaped = await q.reap_stale(session, older_than_minutes=stale_after_minutes)
            if reaped:
                log.warning("queue.reaped", jobs=reaped, stale_after_minutes=stale_after_minutes)
        except Exception:  # a database blip must not kill the reaper
            log.exception("queue.reap_failed")
        await _wait_or_stop(stop, interval_s)


async def _claim_loop(
    stop: asyncio.Event,
    *,
    registry: dict[str, Handler],
    kinds: Sequence[str],
    worker_id: str,
    concurrency: int,
    inflight: set[asyncio.Task[None]],
    poll_interval_s: float,
    max_idle_sleep_s: float,
) -> None:
    sleep_s = poll_interval_s
    while not stop.is_set():
        free = concurrency - len(inflight)
        if free <= 0:
            await _wait_or_stop(stop, 0.05)
            continue

        try:
            async with get_session() as session:
                claimed = await q.claim(session, kinds, worker_id, limit=free)
        except Exception:  # survive a Postgres failover / restart
            log.exception("queue.claim_failed")
            await _wait_or_stop(stop, max_idle_sleep_s)
            continue

        if not claimed:
            await _wait_or_stop(stop, sleep_s)
            # Back off while idle so an empty queue is not a constant `UPDATE`
            # against a table that is already the churn hotspot of the database.
            sleep_s = min(sleep_s * 2, max_idle_sleep_s)
            continue

        sleep_s = poll_interval_s
        for job in claimed:
            task = asyncio.create_task(_run_one(job, registry), name=f"job-{job.id}")
            # Strong ref until done; without it the task can be GC'd mid-flight.
            inflight.add(task)
            task.add_done_callback(functools.partial(_job_task_done, inflight))


async def _drain(inflight: set[asyncio.Task[None]], grace_s: float) -> None:
    if not inflight:
        return
    log.info("worker.draining", jobs=len(inflight), grace_s=grace_s)
    _, pending = await asyncio.wait(set(inflight), timeout=grace_s)
    if not pending:
        return
    log.warning("worker.drain_timeout", jobs=len(pending))
    for task in pending:
        task.cancel()
    # _run_one's CancelledError branch needs a moment to release the leases.
    await asyncio.wait(pending, timeout=10.0)


async def run_worker(
    *,
    kinds: Sequence[str] | None = None,
    concurrency: int = 4,
    worker_id: str = WORKER_ID,
    poll_interval_s: float = 1.0,
    max_idle_sleep_s: float = 5.0,
    reap_interval_s: float = 60.0,
    stale_after_minutes: int = 30,
    shutdown_grace_s: float = 30.0,
    registry: dict[str, Handler] | None = None,
) -> None:
    """Run until SIGINT/SIGTERM, then drain.

    Args:
        kinds: Job kinds to claim. Defaults to exactly what this process can
            handle — claiming a kind with no handler only dead-letters it, so a
            worker must never ask for work it cannot do.
        concurrency: Maximum jobs in flight. Also the claim batch size, since
            claiming more than can be started locks work away from siblings.
        stale_after_minutes: Lease length used by the reaper. Must be longer than
            the slowest handler.
    """
    handlers = HANDLERS if registry is None else registry
    if not handlers:
        # An empty registry means the handler modules never got imported. Failing
        # loudly beats a process that polls forever and completes nothing.
        raise ValueError("no job handlers registered")
    claim_kinds = list(kinds) if kinds else sorted(handlers)

    unknown = sorted(set(claim_kinds) - set(handlers))
    if unknown:
        raise ValueError(f"no handler registered for requested kinds: {', '.join(unknown)}")

    stop = asyncio.Event()
    _install_signal_handlers(stop)
    inflight: set[asyncio.Task[None]] = set()

    log.info("worker.started", worker_id=worker_id, kinds=claim_kinds, concurrency=concurrency)
    try:
        # The two long-lived loops are siblings: the reaper must keep running
        # while the claimer is asleep on an empty queue.
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_reap_loop(stop, reap_interval_s, stale_after_minutes), name="reaper")
            tg.create_task(
                _claim_loop(
                    stop,
                    registry=handlers,
                    kinds=claim_kinds,
                    worker_id=worker_id,
                    concurrency=concurrency,
                    inflight=inflight,
                    poll_interval_s=poll_interval_s,
                    max_idle_sleep_s=max_idle_sleep_s,
                ),
                name="claimer",
            )
    finally:
        # Job tasks are deliberately *not* in the TaskGroup: the group would wait
        # for them without a deadline, so a hung handler would block shutdown
        # forever. Drain them here with a bounded grace period instead.
        await _drain(inflight, shutdown_grace_s)
        log.info("worker.stopped", worker_id=worker_id)


def main(
    kinds: Sequence[str] | None = None,
    *,
    concurrency: int = 4,
    handler_modules: Sequence[str] = HANDLER_MODULES,
) -> None:
    """Console-script entry point for the background worker."""

    async def _main() -> None:
        try:
            await run_worker(kinds=kinds, concurrency=concurrency)
        finally:
            # Before the loop closes, or asyncpg is left holding sockets bound to
            # a dead loop and shutdown ends in a wall of tracebacks.
            await dispose_engine()

    load_handler_modules(handler_modules)
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()
