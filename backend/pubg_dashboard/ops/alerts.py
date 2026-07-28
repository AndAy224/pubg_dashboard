"""Open, refresh and close operational alerts.

One row per open `kind`, upserted through the partial unique index over
unresolved rows. The `ON CONFLICT` predicate below must match that index's
predicate **character for character** or Postgres will not infer it — the same
trap `uq_jobs_dedupe_live` documents.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.db.models import OpsAlert, OpsHeartbeat, utcnow

log = structlog.get_logger(__name__)

__all__ = ["beat", "heartbeat_age_s", "open_alerts", "raise_alert", "resolve_alert"]


async def raise_alert(session: AsyncSession, kind: str, detail: str) -> None:
    """Open `kind`, or refresh it if it is already open.

    Refreshing rather than re-opening is what keeps a stalled poller one row
    with a rising `observations` count instead of one row per check.
    """
    stmt = (
        pg_insert(OpsAlert)
        .values(kind=kind, detail=detail, opened_at=utcnow(), last_seen_at=utcnow())
        .on_conflict_do_update(
            index_elements=[OpsAlert.kind],
            index_where=text("resolved_at IS NULL"),
            set_={
                "last_seen_at": utcnow(),
                "detail": detail,
                "observations": OpsAlert.observations + 1,
            },
        )
    )
    await session.execute(stmt)
    log.error("ops.alert", kind=kind, detail=detail)


async def resolve_alert(session: AsyncSession, kind: str) -> None:
    """Close `kind` if it is open. A no-op otherwise.

    Closing rather than deleting keeps the history of distinct incidents, and
    the partial index means the next occurrence opens a fresh row.
    """
    result = await session.execute(
        update(OpsAlert)
        .where(OpsAlert.kind == kind, OpsAlert.resolved_at.is_(None))
        .values(resolved_at=utcnow())
    )
    if result.rowcount:
        log.info("ops.alert.resolved", kind=kind)


async def open_alerts(session: AsyncSession) -> list[OpsAlert]:
    rows = await session.execute(
        select(OpsAlert).where(OpsAlert.resolved_at.is_(None)).order_by(OpsAlert.opened_at)
    )
    return list(rows.scalars().all())


async def beat(session: AsyncSession, name: str) -> None:
    """Record that `name` ran just now."""
    await session.execute(
        pg_insert(OpsHeartbeat)
        .values(name=name, at=utcnow())
        .on_conflict_do_update(index_elements=[OpsHeartbeat.name], set_={"at": utcnow()})
    )


async def heartbeat_age_s(session: AsyncSession, name: str) -> float | None:
    """Seconds since `name` last reported, or None if it never has.

    None is **not** "fine". A watchdog that has never run and a watchdog that
    stopped an hour ago are both reasons to look, and the caller must treat
    them as such rather than as a missing value.
    """
    at = await session.scalar(select(OpsHeartbeat.at).where(OpsHeartbeat.name == name))
    if at is None:
        return None
    return (utcnow() - at).total_seconds()
