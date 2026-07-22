"""Object-storage abstraction and the canonical key naming convention.

Two kinds of blob live in storage:

* **raw telemetry** — the event stream exactly as the PUBG CDN served it, kept
  gzipped on disk/in the bucket. Measured over the 61-match corpus: ~1.9 MB
  median / 2.5 MB max gzipped, inflating to 21-32 MB of JSON. It is never
  stored inflated — that is a 13x storage bill for bytes nothing reads
  directly.
* **replay bundles** — the parser's MessagePack output, also gzipped, versioned
  by parser version so a parser upgrade can re-emit without re-downloading
  telemetry (PUBG only retains telemetry for 14 days; the raw copy is the only
  thing that makes reprocessing possible at all).

Key convention
--------------
::

    telemetry/{shard}/{yyyy}/{mm}/{match_id}.json.gz
    replay/v{parser_version}/{match_id}.msgpack.gz

Telemetry is partitioned by the match's **UTC played_at**, not by ingest time,
so `raw_telemetry_retention_days` expiry is a prefix scan: whole expired months
are `telemetry/{shard}/{yyyy}/{mm}/` prefixes that can be listed and deleted
without walking the bucket. Only the boundary month needs per-object dates.

Replay bundles are partitioned by parser version instead, because their
retention rule is different: they expire when the parser version does, all at
once, as the `replay/v{n}/` prefix.

Note for the telemetry fetcher
------------------------------
`put()` stores bytes verbatim. The CDN sends telemetry with
`Content-Encoding: gzip` and httpx *transparently inflates* `response.content`,
so a fetcher that hands us `response.content` would store inflated JSON under a
`.json.gz` key. Read the raw stream (`response.aiter_raw()` / `iter_raw()`) to
get the original gzip frame, or use `put_compressed()` to re-compress.
"""

from __future__ import annotations

import abc
import asyncio
import datetime as dt
import gzip
import re
from collections.abc import AsyncIterator

__all__ = [
    "GZIP_CONTENT_TYPE",
    "MSGPACK_CONTENT_TYPE",
    "ObjectNotFoundError",
    "Storage",
    "StorageError",
    "replay_key",
    "replay_prefix",
    "telemetry_key",
    "telemetry_prefix",
    "validate_key",
]

# Both artefacts are gzip frames on the wire and at rest. We deliberately do
# NOT advertise `Content-Encoding: gzip` on them: the gzip frame *is* the
# object, and some HTTP clients (browsers hitting a presigned URL, CDNs) would
# silently inflate it, which breaks byte-for-byte `size()` accounting against
# `matches.telemetry_bytes`.
GZIP_CONTENT_TYPE = "application/gzip"
MSGPACK_CONTENT_TYPE = "application/vnd.msgpack"

# Keys are always POSIX-style, lowercase-ish, and drawn from a character set
# that is safe as a Windows path component (the filesystem backend maps keys
# straight onto disk). Backslashes are rejected outright so a caller cannot
# smuggle a native Windows path in, and "." components block traversal.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class StorageError(RuntimeError):
    """Any storage-layer failure."""


class ObjectNotFoundError(StorageError):
    """The key does not exist. Raised by `get()` and `size()`, never `delete()`."""

    def __init__(self, key: str) -> None:
        super().__init__(f"object not found: {key}")
        self.key = key


def validate_key(key: str) -> str:
    """Reject keys that would escape the storage root or break on Windows."""
    if not _KEY_RE.match(key) or "//" in key or key.endswith("/"):
        raise StorageError(f"invalid storage key: {key!r}")
    # ".." never appears as a *component* under our conventions; catching it as
    # a component (not a substring) still allows a legitimate "a..b" filename.
    if any(part in {".", ".."} for part in key.split("/")):
        raise StorageError(f"invalid storage key (path traversal): {key!r}")
    return key


def telemetry_key(shard: str, match_id: str, played_at: dt.datetime) -> str:
    """`telemetry/{shard}/{yyyy}/{mm}/{match_id}.json.gz`.

    `played_at` is normalised to UTC first. A naive datetime is *assumed* UTC —
    everything the PUBG API emits is Zulu, and DB columns are timestamptz, so a
    naive value here means someone stripped the tzinfo, not that it is local.
    """
    when = played_at.astimezone(dt.UTC) if played_at.tzinfo else played_at.replace(tzinfo=dt.UTC)
    return validate_key(f"telemetry/{shard}/{when:%Y}/{when:%m}/{match_id}.json.gz")


def telemetry_prefix(
    shard: str | None = None, year: int | None = None, month: int | None = None
) -> str:
    """Prefix for a retention/backfill scan. Narrows left to right."""
    if shard is None:
        return "telemetry/"
    if year is None:
        return f"telemetry/{shard}/"
    if month is None:
        return f"telemetry/{shard}/{year:04d}/"
    return f"telemetry/{shard}/{year:04d}/{month:02d}/"


def replay_key(parser_version: int, match_id: str) -> str:
    """`replay/v{parser_version}/{match_id}.msgpack.gz`."""
    return validate_key(f"replay/v{parser_version}/{match_id}.msgpack.gz")


def replay_prefix(parser_version: int | None = None) -> str:
    """Prefix covering every bundle a given parser version produced."""
    return "replay/" if parser_version is None else f"replay/v{parser_version}/"


class Storage(abc.ABC):
    """Async blob store. Implementations must be safe to share across tasks."""

    # --- primitives (implemented per backend) -------------------------------
    @abc.abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = GZIP_CONTENT_TYPE) -> None:
        """Write `data` at `key`, overwriting. Must be atomic: a crashed write
        may not leave a truncated object that a later `exists()` accepts."""

    @abc.abstractmethod
    async def get(self, key: str) -> bytes:
        """Raise `ObjectNotFoundError` if absent."""

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None:
        """Idempotent — deleting a missing key is a no-op, not an error."""

    @abc.abstractmethod
    async def size(self, key: str) -> int:
        """Stored (compressed) byte count. Raise `ObjectNotFoundError` if absent."""

    @abc.abstractmethod
    def iter_keys(self, prefix: str) -> AsyncIterator[str]:
        """Yield keys under `prefix`, in unspecified order. Drives retention."""

    async def aclose(self) -> None:
        """Release backend resources. Safe to call more than once.

        Not abstract: backends with nothing to release (the filesystem one)
        should not be forced to write an empty override.
        """
        return None

    # --- shared conveniences ------------------------------------------------
    async def get_decompressed(self, key: str) -> bytes:
        """Fetch a `.gz` object and inflate it.

        Inflation happens in a worker thread. It is ~37 ms of uninterruptible
        CPU for the largest match in the corpus (2.5 MB -> 32 MB), and the
        parser does it in a loop over a backlog, so on the event loop it turns
        into seconds of stalled requests.
        """
        raw = await self.get(key)
        return await asyncio.to_thread(gzip.decompress, raw)

    async def put_compressed(
        self,
        key: str,
        data: bytes,
        content_type: str = GZIP_CONTENT_TYPE,
        *,
        level: int = 6,
    ) -> int:
        """Gzip `data` (in a thread) and store it. Returns the stored size.

        For raw telemetry prefer `put()` with the CDN's original gzip frame —
        re-compressing costs CPU for no benefit. This exists for artefacts we
        generate ourselves, i.e. the MessagePack replay bundles.
        """
        blob = await asyncio.to_thread(gzip.compress, data, level)
        await self.put(key, blob, content_type)
        return len(blob)

    async def delete_prefix(self, prefix: str) -> int:
        """Delete everything under `prefix`. Returns the count deleted."""
        deleted = 0
        async for key in self.iter_keys(prefix):
            await self.delete(key)
            deleted += 1
        return deleted
