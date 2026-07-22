"""Alembic environment, wired to the asyncpg engine.

Alembic's migration API is entirely synchronous. The bridge is
`AsyncConnection.run_sync(...)`: it runs a sync callable inside SQLAlchemy's
greenlet, so the plain `Connection` that callable receives can still perform IO
against the async driver. Nothing inside `do_run_migrations` may be awaited.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_engine_from_config

from alembic import context
from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The DSN comes from Settings (repo-root `.env`), never from alembic.ini, so the
# migrations and the app cannot end up pointed at different databases and no
# password is committed. alembic.ini values are read back through ConfigParser
# interpolation, so a literal '%' — routine in a URL-encoded password — has to be
# doubled or `get_main_option` blows up with an InterpolationSyntaxError.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = Base.metadata

# Indexes Alembic cannot round-trip. It does not compare a partial index's WHERE
# predicate, and expression indexes reflect back in a form that rarely matches
# the model, so autogenerate emits spurious drop/create pairs (or, worse, a plain
# full index that quietly replaces the partial one). These are owned by
# hand-written migrations; changing a predicate means writing a new revision by
# hand, not re-running autogenerate.
HAND_MANAGED_INDEXES: frozenset[str] = frozenset(
    {
        "ix_players_poll_queue",  # partial: WHERE tracked
        "ix_players_name_lower",  # functional: lower(name)
        "ix_matches_official_played_at",  # partial: WHERE match_type = 'official'
        "ix_matches_needs_telemetry",  # partial: WHERE telemetry_key IS NULL
        "ix_matches_needs_parse",  # partial: fetched but not yet parsed
        "ix_participants_human",  # partial: WHERE NOT is_bot
        "uq_jobs_dedupe_live",  # partial UNIQUE: WHERE state IN (pending, running)
        "ix_jobs_claim",  # partial: WHERE state = 'pending'
        "ix_kill_killer",  # partial: WHERE killer_account_id IS NOT NULL
        "ix_kill_weapon",  # partial: WHERE killer_account_id IS NOT NULL
    }
)

# Serialises concurrent `alembic upgrade head` calls — two containers starting at
# once would otherwise both try to CREATE TABLE. The key is arbitrary but must be
# stable. `_xact_` releases it at commit/rollback, so a crashed migration cannot
# leave the lock held.
_ADVISORY_LOCK_KEY = 823041


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Autogenerate filter — see HAND_MANAGED_INDEXES."""
    return not (type_ == "index" and name in HAND_MANAGED_INDEXES)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (`alembic upgrade --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Synchronous body of a migration run. Do not await anything in here."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_ADVISORY_LOCK_KEY})")
        context.run_migrations()


async def run_async_migrations() -> None:
    # Tests hand us a live AsyncConnection through Config.attributes so the
    # schema is built inside the same transaction the test later rolls back.
    injected: AsyncConnection | None = config.attributes.get("connection")
    if injected is not None:
        await injected.run_sync(do_run_migrations)
        return

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # A migration run is one short-lived connection; pooling it only risks
        # leaving a socket open past the end of asyncio.run().
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
