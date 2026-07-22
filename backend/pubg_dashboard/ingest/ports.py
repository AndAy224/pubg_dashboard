"""Dependency seams for the ingestion pipeline.

`ingest` reaches the PUBG API and object storage through Protocols instead of
concrete imports. Two reasons: the pipeline is unit-testable against fakes
without a network or a bucket, and it does not break at import time while the
concrete `pubg.client` / `storage` modules are still being written.

Anything implementing these Protocols can be dropped into `IngestContext`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pubg_dashboard.config import Settings


@runtime_checkable
class PubgApi(Protocol):
    """The slice of the PUBG client the ingestion pipeline uses."""

    shard: str

    async def get_players_by_names(self, names: Sequence[str]) -> dict[str, Any]:
        """`GET /players?filter[playerNames]=`, at most 10 names, comma separated.

        Names are CASE-SENSITIVE and an unknown name 404s the *whole* batch —
        the poller relies on that 404 surfacing as an exception carrying a
        `.status_code` (or an httpx-style `.response.status_code`) so it can
        binary-split the batch and find the offender.

        Rate limited: this call costs one token from the shared bucket.
        """
        ...

    async def get_players_by_ids(self, account_ids: Sequence[str]) -> dict[str, Any]:
        """`GET /players?filter[playerIds]=`, at most 10 ids. Rate limited.

        Preferred over names for backfill: account ids survive a rename.
        """
        ...

    async def get_match(self, match_id: str) -> dict[str, Any]:
        """`GET /matches/{id}`.

        This endpoint returns no rate-limit headers and is not rate limited, so
        the implementation MUST NOT spend a token from the limiter here.
        """
        ...

    async def download_telemetry(self, url: str) -> bytes:
        """Fetch a telemetry asset from the CDN.

        The CDN is unauthenticated and unlimited: the implementation must NOT
        send the `Authorization` header (that would leak the API key into a
        third party's access log) and must NOT take a rate-limit token.

        The return value may be raw gzip bytes or already-decoded JSON
        depending on whether the client used `aiter_raw()` or `aiter_bytes()`;
        callers here normalise via the gzip magic number rather than guessing.
        """
        ...


class TelemetryStore(Protocol):
    """Object storage for raw gzipped telemetry (MinIO/S3 or a local dir)."""

    def key_for(self, shard: str, match_id: str, played_at: dt.datetime) -> str:
        """Deterministic storage key. Must be stable across processes.

        `shard` and `played_at` are parameters, not conveniences: the layout is
        `telemetry/{shard}/{yyyy}/{mm}/{match_id}.json.gz`, and the retention
        and backfill scans narrow on that prefix. A key derived from `match_id`
        alone would flatten the hierarchy those scans walk.
        """
        ...

    async def exists(self, key: str) -> bool: ...

    async def put(self, key: str, data: bytes) -> int:
        """Store `data` (already gzipped) and return the number of bytes written."""
        ...


class JobLike(Protocol):
    """A claimed row from the `jobs` table, as handed to a handler by the worker."""

    @property
    def id(self) -> int: ...

    @property
    def kind(self) -> str: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...


Handler = Callable[[JobLike], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class IngestContext:
    """Process-wide wiring handed to the poller, the handlers and the importer.

    Holds a *sessionmaker*, never a session: one `AsyncSession` per task is a
    hard requirement under asyncio, and handlers run concurrently.
    """

    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    api: PubgApi
    storage: TelemetryStore | None = None

    def require_storage(self) -> TelemetryStore:
        if self.storage is None:
            raise RuntimeError(
                "IngestContext.storage is not configured; telemetry handlers need it"
            )
        return self.storage
