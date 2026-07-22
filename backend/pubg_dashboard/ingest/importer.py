"""Import the panic-archive corpus without touching the network.

`scripts/panic_archive.py` raced PUBG's 14-day retention and dumped raw match
JSON to `data/matches/` plus gzipped telemetry to `data/telemetry/`. Those
matches are already expired upstream — the API cannot serve them again — so
this is the only path by which they enter the database.

Idempotent and resumable: it commits per match, skips matches whose telemetry
is already registered, and can be re-run after a crash or a partial run.
"""

from __future__ import annotations

import asyncio
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import orjson
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pubg_dashboard.config import get_settings
from pubg_dashboard.db.models import Match, utcnow
from pubg_dashboard.ingest.ports import TelemetryStore
from pubg_dashboard.ingest.queue import JOB_PARSE_TELEMETRY, dedupe_key, enqueue
from pubg_dashboard.ingest.upsert import upsert_match

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class ImportReport:
    matches_seen: int = 0
    matches_ingested: int = 0
    telemetry_registered: int = 0
    telemetry_skipped: int = 0
    telemetry_missing: int = 0
    failed: int = 0


async def import_archive(
    session: AsyncSession,
    *,
    storage: TelemetryStore | None = None,
    matches_dir: pathlib.Path | None = None,
    telemetry_dir: pathlib.Path | None = None,
    queue_parse: bool = True,
) -> ImportReport:
    """Ingest every archived match and register its telemetry.

    With `storage=None` the `.json.gz` files are registered **in place**:
    `telemetry_key` becomes the file name relative to `settings.telemetry_dir`,
    which is exactly the filesystem-backend contract. Pass a `storage` when the
    deployment is backed by MinIO/S3, or the recorded keys will point at
    objects the bucket does not have.
    """
    settings = get_settings()
    matches_dir = matches_dir or settings.match_archive_dir
    telemetry_dir = telemetry_dir or settings.telemetry_dir

    if storage is None and settings.storage_backend != "filesystem":
        log.warning(
            "import.no_storage_backend",
            storage_backend=settings.storage_backend,
            detail="registering telemetry in place; pass storage= to upload it",
        )

    report = ImportReport()
    files: Sequence[pathlib.Path] = sorted(matches_dir.glob("*.json"))
    log.info("import.start", matches=len(files), matches_dir=str(matches_dir))

    for path in files:
        report.matches_seen += 1
        try:
            await _import_one(
                session,
                path,
                telemetry_dir=telemetry_dir,
                storage=storage,
                queue_parse=queue_parse,
                report=report,
            )
        except Exception:  # noqa: BLE001 - one bad file must not abort the corpus
            report.failed += 1
            # The failed match left a dirty transaction behind; drop it so the
            # next file starts clean instead of erroring with "transaction has
            # been rolled back".
            await session.rollback()
            log.exception("import.match_failed", path=str(path))

    log.info(
        "import.done",
        seen=report.matches_seen,
        ingested=report.matches_ingested,
        telemetry_registered=report.telemetry_registered,
        telemetry_skipped=report.telemetry_skipped,
        telemetry_missing=report.telemetry_missing,
        failed=report.failed,
    )
    return report


async def _import_one(
    session: AsyncSession,
    path: pathlib.Path,
    *,
    telemetry_dir: pathlib.Path,
    storage: TelemetryStore | None,
    queue_parse: bool,
    report: ImportReport,
) -> None:
    # orjson parses these several times faster than the stdlib; reading off the
    # loop keeps a 20 MB file from stalling everything else in the process.
    raw = await asyncio.to_thread(path.read_bytes)
    payload: dict[str, Any] = orjson.loads(raw)

    match = await upsert_match(session, payload)
    match_id = match.match_id
    report.matches_ingested += 1

    telemetry_path = telemetry_dir / f"{match_id}.json.gz"
    if not telemetry_path.exists():
        report.telemetry_missing += 1
        await session.commit()
        return

    existing_key = match.telemetry_key
    if existing_key and (storage is None or await storage.exists(existing_key)):
        report.telemetry_skipped += 1
    else:
        key, size = await _register_telemetry(match_id, telemetry_path, storage)
        await session.execute(
            update(Match)
            .where(Match.match_id == match_id)
            .values(
                telemetry_key=key,
                telemetry_bytes=size,
                # Keep the original timestamp on a re-run: this records when we
                # first had the bytes, not when we last looked at the file.
                telemetry_fetched_at=func.coalesce(Match.telemetry_fetched_at, utcnow()),
            )
        )
        report.telemetry_registered += 1

    if queue_parse:
        await enqueue(
            session,
            JOB_PARSE_TELEMETRY,
            {"match_id": match_id},
            key=dedupe_key(JOB_PARSE_TELEMETRY, match_id),
        )

    # Commit per match: 61 matches x ~100 participants in one transaction would
    # be all-or-nothing, and this needs to be resumable.
    await session.commit()


async def _register_telemetry(
    match_id: str,
    telemetry_path: pathlib.Path,
    storage: TelemetryStore | None,
) -> tuple[str, int]:
    """Put the archived `.json.gz` into storage, or register it where it lies."""
    if storage is None:
        # Filesystem backend: the file already sits under settings.telemetry_dir
        # under exactly the name the store would have chosen. Nothing to copy.
        return telemetry_path.name, telemetry_path.stat().st_size

    # panic_archive.py wrote gzip.compress(response.content), so these are
    # genuine .gz bytes and go to the store untouched.
    blob = await asyncio.to_thread(telemetry_path.read_bytes)
    key = storage.key_for(match_id)
    size = await storage.put(key, blob)
    return key, size


def archived_match_ids(matches_dir: pathlib.Path | None = None) -> list[str]:
    """Match ids present in the on-disk archive (the file stem is the id)."""
    matches_dir = matches_dir or get_settings().match_archive_dir
    return sorted(path.stem for path in matches_dir.glob("*.json"))


async def unimported_archive_ids(
    session: AsyncSession, matches_dir: pathlib.Path | None = None
) -> list[str]:
    """Archive ids not yet in the database — a cheap progress/resume check."""
    ids = archived_match_ids(matches_dir)
    if not ids:
        return []
    known = set((await session.scalars(select(Match.match_id).where(Match.match_id.in_(ids)))).all())
    return [match_id for match_id in ids if match_id not in known]
