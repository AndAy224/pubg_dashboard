"""Async engine + session plumbing.

One :class:`AsyncEngine` per **process**, created lazily and shared by the API
workers, the poller and the job worker. Two rules drive everything here:

1. ``expire_on_commit=False``. Under asyncio the default (``True``) expires every
   attribute at commit, so the next attribute access emits lazy IO outside a
   greenlet context and raises ``MissingGreenlet``. The job queue depends on this
   directly: :func:`pubg_dashboard.queue.jobs.claim` commits immediately to drop
   the ``SKIP LOCKED`` row locks and then hands the still-populated ``Job``
   objects to the worker.
2. One ``AsyncSession`` per task. A session is *not* safe to share across
   concurrent tasks, so every in-flight job opens its own via :func:`get_session`.

The engine is bound to the event loop that first opened a connection. Create it
inside ``asyncio.run(...)`` (or a FastAPI lifespan) and dispose it before that
loop closes, or asyncpg leaves sockets attached to a dead loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pubg_dashboard.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(dsn: str, application_name: str) -> dict[str, Any]:
    """Driver-specific connect args, applied only when the driver is asyncpg.

    ``server_settings`` is asyncpg's spelling of libpq options; passing it to any
    other driver is a ``TypeError`` at connect time, and the DSN is a plain
    settings string that a deployer can point at psycopg or a test harness.
    """
    if not make_url(dsn).drivername.endswith("asyncpg"):
        return {}
    return {
        "server_settings": {
            # Shows up in pg_stat_activity — the only way to tell the API's
            # connections from the worker's during an incident.
            "application_name": application_name,
            # PG's JIT costs more to plan than it saves on short OLTP queries,
            # and every query in this app is short.
            "jit": "off",
        },
        "timeout": 10,  # TCP connect timeout, seconds
    }


def init_engine(
    dsn: str | None = None,
    *,
    application_name: str = "pubg-dashboard",
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
) -> AsyncEngine:
    """Create the process-wide engine + sessionmaker. Idempotent.

    Calling it twice returns the existing engine rather than leaking a second
    connection pool, so a worker that also mounts the API cannot double-pool.
    """
    global _engine, _sessionmaker

    if _engine is not None:
        return _engine

    url = dsn or get_settings().database_url
    _engine = create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=30,
        pool_recycle=1800,  # recycle before any router/proxy idle timeout kills the socket
        pool_pre_ping=True,
        connect_args=_connect_args(url, application_name),
    )
    _sessionmaker = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,  # see module docstring — not optional under asyncio
        # The queue helpers issue explicit DML; an implicit flush before every
        # SELECT would only add surprise ordering.
        autoflush=False,
    )
    return _engine


def get_engine() -> AsyncEngine:
    """The process engine, creating it on first use."""
    if _engine is None:
        return init_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    if _sessionmaker is None:  # pragma: no cover - init_engine always sets it
        raise RuntimeError("engine initialisation did not produce a sessionmaker")
    return _sessionmaker


async def dispose_engine() -> None:
    """Close every pooled connection and forget the engine.

    Must run before the owning event loop closes. After this the next
    :func:`get_engine` builds a fresh engine, which is what makes the worker
    restartable inside one interpreter (and what makes tests isolable).
    """
    global _engine, _sessionmaker

    engine, _engine, _sessionmaker = _engine, None, None
    if engine is not None:
        await engine.dispose()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Open one session for one unit of work.

    Does **not** commit: the caller decides. Exiting the block closes the session
    and rolls back anything still uncommitted.
    """
    maker = get_sessionmaker()
    async with maker() as session:
        yield session


async def session_dep() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: ``session: AsyncSession = Depends(session_dep)``.

    Prefer the :data:`SessionDep` alias below.
    """
    async with get_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(session_dep)]
