"""Ingest visibility and the two operations that spend rate-limit budget."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from pubg_dashboard.api.schemas import IngestStatus, QueueRow
from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Job, Match, Player
from pubg_dashboard.db.session import SessionDep
from pubg_dashboard.ingest.queue import (
    JOB_BACKFILL_PLAYER,
    JOB_PARSE_TELEMETRY,
    dedupe_key,
    enqueue,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/status", response_model=IngestStatus)
async def ingest_status(session: SessionDep) -> IngestStatus:
    queue = [
        QueueRow(kind=k, state=s, count=n)
        for k, s, n in (
            await session.execute(
                select(Job.kind, Job.state, func.count())
                .group_by(Job.kind, Job.state)
                .order_by(Job.kind, Job.state)
            )
        ).all()
    ]
    tracked = await session.scalar(
        select(func.count()).select_from(Player).where(Player.tracked)
    )
    matches = await session.scalar(select(func.count()).select_from(Match))
    unparsed = await session.scalar(
        select(func.count())
        .select_from(Match)
        .where(Match.telemetry_key.is_not(None), Match.telemetry_parsed_at.is_(None))
    )
    oldest = await session.scalar(
        select(func.min(Match.played_at)).where(
            Match.telemetry_key.is_not(None), Match.telemetry_parsed_at.is_(None)
        )
    )
    lag = await session.scalar(
        select(func.min(func.extract("epoch", func.now() - Player.last_polled_at))).where(
            Player.tracked, Player.last_polled_at.is_not(None)
        )
    )
    return IngestStatus(
        queue=queue,
        tracked_players=tracked or 0,
        matches=matches or 0,
        unparsed=unparsed or 0,
        oldest_unparsed=oldest,
        poller_lag_s=float(lag) if lag is not None else None,
        rate_limit_per_min=get_settings().pubg_rate_limit_per_min,
    )


@router.post("/backfill/{account_id}", status_code=202)
async def backfill(session: SessionDep, account_id: str) -> dict[str, object]:
    """Queue a history sweep for one player.

    Costs one rate-limited request when the worker picks it up; every match it
    then discovers is fetched for free.
    """
    exists = await session.scalar(
        select(func.count()).select_from(Player).where(Player.account_id == account_id)
    )
    if not exists:
        raise HTTPException(404, f"unknown player {account_id}")

    job = await enqueue(
        session,
        JOB_BACKFILL_PLAYER,
        {"account_id": account_id},
        key=dedupe_key(JOB_BACKFILL_PLAYER, account_id),
    )
    await session.commit()
    # `False` means an identical job was already live. That is the normal
    # outcome of a double-click, not an error.
    return {"queued": bool(job), "accountId": account_id}


@router.post("/reparse", status_code=202)
async def reparse(
    session: SessionDep,
    match_id: Annotated[
        str | None, Query(alias="matchId", description="Omit to requeue everything.")
    ] = None,
    stale_only: Annotated[
        bool,
        Query(alias="staleOnly", description="Only matches parsed by an older parser version."),
    ] = True,
) -> dict[str, object]:
    """Requeue `parse_telemetry`.

    Free: it reads raw telemetry back out of object storage and never touches
    the API. This is what makes a parser improvement apply to the whole archive
    retroactively.

    Reparsing is idempotent — each parse records what it contributed to the
    heatmap and the next one subtracts that before adding its own.
    """
    from pubg_dashboard.telemetry.bundle import PARSER_VERSION

    stmt = select(Match.match_id).where(Match.telemetry_key.is_not(None))
    if match_id:
        stmt = stmt.where(Match.match_id == match_id)
    elif stale_only:
        stmt = stmt.where(
            (Match.parser_version.is_(None)) | (Match.parser_version < PARSER_VERSION)
        )

    ids = [row[0] for row in (await session.execute(stmt)).all()]
    queued = 0
    for mid in ids:
        if await enqueue(
            session,
            JOB_PARSE_TELEMETRY,
            {"match_id": mid},
            key=dedupe_key(JOB_PARSE_TELEMETRY, mid),
        ):
            queued += 1
    await session.commit()
    return {"matched": len(ids), "queued": queued, "parserVersion": PARSER_VERSION}
