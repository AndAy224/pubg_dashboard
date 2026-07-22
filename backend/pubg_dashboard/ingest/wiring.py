"""Composition root for the ingestion pipeline.

`ingest` talks to the PUBG API through the :class:`~pubg_dashboard.ingest.ports.PubgApi`
Protocol, and nothing in the tree ever built one. That is the gap this module
closes: :class:`PubgApiAdapter` maps the concrete
:class:`~pubg_dashboard.pubg.client.PubgClient` onto that port, and
:func:`build_context` assembles the :class:`~pubg_dashboard.ingest.ports.IngestContext`
the poller, the handlers and the worker all take.

**Why an adapter and not a rename.** The two sides disagree on purpose, and
both are right for their own job:

* The client returns **parsed pydantic models** and streams telemetry to a
  file, never buffering a ~19 MB body.
* The ingest layer wants **raw JSON:API dicts**, because `upsert` and
  `parse_players_payload` are verified field-by-field against the archived
  corpus in exactly that form.

Collapsing either into the other would trade a measured contract for a derived
one. The adapter is the honest seam, and it is small.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
from collections.abc import Sequence
from typing import Any

from pubg_dashboard.config import Settings, get_settings
from pubg_dashboard.db.session import get_sessionmaker
from pubg_dashboard.ingest.ports import IngestContext, TelemetryStore
from pubg_dashboard.pubg.client import PubgClient
from pubg_dashboard.storage.base import Storage, telemetry_key

__all__ = ["PubgApiAdapter", "TelemetryStoreAdapter", "build_context"]


class PubgApiAdapter:
    """Presents a :class:`PubgClient` as the :class:`PubgApi` port."""

    def __init__(self, client: PubgClient) -> None:
        self._client = client

    @property
    def shard(self) -> str:
        return self._client.shard

    async def get_players_by_names(self, names: Sequence[str]) -> dict[str, Any]:
        return await self._client.get_players_payload(names, by="names")

    async def get_players_by_ids(self, account_ids: Sequence[str]) -> dict[str, Any]:
        return await self._client.get_players_payload(account_ids, by="ids")

    async def get_match(self, match_id: str) -> dict[str, Any]:
        # Unmetered endpoint — get_match_payload passes keyed=False, so this
        # must never be made to spend a rate-limit token.
        return await self._client.get_match_payload(match_id)

    async def download_telemetry(self, url: str) -> bytes:
        """Fetch one telemetry asset and return it as gzip bytes.

        The client streams to disk rather than buffering the body, which is what
        keeps a concurrent backfill from holding several 19 MB JSON blobs in
        memory at once. The port's contract is `bytes`, so the file is read back
        — but it is read back *compressed* (~2 MB), never decoded.
        """
        with tempfile.TemporaryDirectory(prefix="pubgd-telemetry-") as tmp:
            dest = pathlib.Path(tmp) / "telemetry.json.gz"
            await self._client.download_telemetry(url, dest)
            return dest.read_bytes()

    async def aclose(self) -> None:
        await self._client.aclose()


class TelemetryStoreAdapter:
    """Presents a :class:`Storage` backend as the :class:`TelemetryStore` port.

    Two small gaps to bridge: key construction is a module-level function in
    `storage.base` rather than a method, and `Storage.put` returns `None` while
    the port reports bytes written (the caller records it as
    `matches.telemetry_bytes`).
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def key_for(self, shard: str, match_id: str, played_at: dt.datetime) -> str:
        return telemetry_key(shard, match_id, played_at)

    async def exists(self, key: str) -> bool:
        return await self._storage.exists(key)

    async def put(self, key: str, data: bytes) -> int:
        # The blob is already gzipped by the caller, so `put` not
        # `put_compressed` — double-compressing would still decode, just larger.
        await self._storage.put(key, data)
        return len(data)


def build_context(
    *,
    settings: Settings | None = None,
    client: PubgClient | None = None,
    storage: TelemetryStore | None = None,
    with_storage: bool = True,
) -> IngestContext:
    """Assemble the process-wide ingestion wiring.

    Args:
        with_storage: `False` for the poller, which only reads `/players` and
            enqueues work. Building storage there would make a MinIO-backed
            deployment refuse to poll whenever the bucket happened to be down,
            for no benefit.
    """
    settings = settings or get_settings()
    api = PubgApiAdapter(client or PubgClient(settings=settings))

    resolved = storage
    if resolved is None and with_storage:
        # Imported here, not at module scope: `storage.factory` pulls in boto3
        # for the minio backend, and the poller has no use for it.
        from pubg_dashboard.storage.factory import get_storage

        resolved = TelemetryStoreAdapter(get_storage())

    return IngestContext(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        api=api,
        storage=resolved,
    )
