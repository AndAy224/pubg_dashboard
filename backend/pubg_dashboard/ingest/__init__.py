"""Ingestion pipeline: poller, job handlers, upsert and archive import.

    poller  --(fetch_match)-->  handlers.fetch_match  --> upsert.upsert_match
                                        |
                                        +--(fetch_telemetry)--> CDN -> storage
                                                                    |
                                                          (parse_telemetry, Phase 3)

`importer.import_archive` is the offline equivalent of the first two steps for
matches PUBG has already expired.
"""

from __future__ import annotations

from pubg_dashboard.ingest.handlers import (
    backfill_player,
    build_handlers,
    fetch_match,
    fetch_telemetry,
    parse_telemetry,
    register_handlers,
)
from pubg_dashboard.ingest.importer import ImportReport, import_archive
from pubg_dashboard.ingest.poller import PollReport, poll_once, run_poller
from pubg_dashboard.ingest.ports import Handler, IngestContext, JobLike, PubgApi, TelemetryStore
from pubg_dashboard.ingest.queue import (
    JOB_BACKFILL_PLAYER,
    JOB_FETCH_MATCH,
    JOB_FETCH_TELEMETRY,
    JOB_PARSE_TELEMETRY,
    dedupe_key,
    enqueue,
    enqueue_match_fetches,
)
from pubg_dashboard.ingest.upsert import (
    parse_match_payload,
    telemetry_url_from_payload,
    unknown_match_ids,
    upsert_match,
)

__all__ = [
    "JOB_BACKFILL_PLAYER",
    "JOB_FETCH_MATCH",
    "JOB_FETCH_TELEMETRY",
    "JOB_PARSE_TELEMETRY",
    "Handler",
    "ImportReport",
    "IngestContext",
    "JobLike",
    "PollReport",
    "PubgApi",
    "TelemetryStore",
    "backfill_player",
    "build_handlers",
    "dedupe_key",
    "enqueue",
    "enqueue_match_fetches",
    "fetch_match",
    "fetch_telemetry",
    "import_archive",
    "parse_match_payload",
    "parse_telemetry",
    "poll_once",
    "register_handlers",
    "run_poller",
    "telemetry_url_from_payload",
    "unknown_match_ids",
    "upsert_match",
]
