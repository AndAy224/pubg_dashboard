"""Backend selection."""

from __future__ import annotations

from functools import lru_cache

from pubg_dashboard.config import get_settings
from pubg_dashboard.storage.base import Storage

__all__ = ["get_storage"]


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    """The process-wide storage handle.

    Cached because the S3 client owns an HTTP connection pool that is expensive
    to rebuild per call. Both backends are safe to share across tasks.

    Tests that swap `storage_backend` must call
    `get_storage.cache_clear()` (and `get_settings.cache_clear()`), same as any
    other lru_cached singleton here.
    """
    # Imported lazily so a filesystem-only deployment never imports boto3.
    match get_settings().storage_backend:
        case "minio":
            from pubg_dashboard.storage.minio import MinioStorage

            return MinioStorage()
        case "filesystem":
            from pubg_dashboard.storage.filesystem import FilesystemStorage

            return FilesystemStorage()
        case unknown:  # pragma: no cover - Settings' Literal already excludes this
            raise ValueError(f"unknown storage_backend: {unknown!r}")
