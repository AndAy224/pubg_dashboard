"""Object storage for raw telemetry and processed replay bundles.

    telemetry/{shard}/{yyyy}/{mm}/{match_id}.json.gz    -- raw, gzipped, verbatim from the CDN
    replay/v{parser_version}/{match_id}.msgpack.gz      -- parser output

See `base.py` for the full rationale behind the key layout.
"""

from __future__ import annotations

from pubg_dashboard.storage.base import (
    GZIP_CONTENT_TYPE,
    MSGPACK_CONTENT_TYPE,
    ObjectNotFoundError,
    Storage,
    StorageError,
    replay_key,
    replay_prefix,
    telemetry_key,
    telemetry_prefix,
    validate_key,
)
from pubg_dashboard.storage.factory import get_storage

__all__ = [
    "GZIP_CONTENT_TYPE",
    "MSGPACK_CONTENT_TYPE",
    "ObjectNotFoundError",
    "Storage",
    "StorageError",
    "get_storage",
    "replay_key",
    "replay_prefix",
    "telemetry_key",
    "telemetry_prefix",
    "validate_key",
]
