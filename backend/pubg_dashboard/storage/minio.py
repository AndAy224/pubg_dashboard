"""S3/MinIO backend.

boto3 is synchronous and blocking, so every call is pushed onto a worker
thread with `asyncio.to_thread`. A telemetry PUT is ~2 MB over the wire and a
backfill does hundreds of them; inline, that freezes the API for the duration.

botocore *clients* are documented as thread-safe once constructed, but
`Session`/client **construction** is not. The client is therefore built eagerly
in `__init__` (sync, at import/DI time) rather than lazily inside a thread,
where two concurrent first-calls could race.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from pubg_dashboard.config import Settings, get_settings
from pubg_dashboard.storage.base import (
    GZIP_CONTENT_TYPE,
    ObjectNotFoundError,
    Storage,
    StorageError,
    validate_key,
)

__all__ = ["MinioStorage"]

# SigV4 requires *a* region even when the endpoint is a local MinIO that has no
# concept of one. "us-east-1" is the only value real S3 accepts implicitly, so
# it is also the only value that lets the same code point at AWS unchanged.
_DEFAULT_REGION = "us-east-1"

# Error codes MinIO/S3 use for "that key/bucket isn't there". head_object
# reports a bare "404" (it has no response body to carry a real code), while
# get_object reports "NoSuchKey" — both must be handled or missing telemetry
# surfaces as an opaque ClientError.
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class MinioStorage(Storage):
    def __init__(self, settings: Settings | None = None, *, max_pool_connections: int = 32) -> None:
        s = settings or get_settings()
        self._bucket = s.minio_bucket
        self._bucket_ready = False
        self._bucket_lock = asyncio.Lock()

        # botocore's urllib3 pool defaults to 10 connections. Every to_thread
        # call above that ceiling blocks *inside the thread* waiting for a
        # connection, which silently caps storage throughput.
        self._client: Any = boto3.client(  # boto3 ships no py.typed; see report note
            "s3",
            endpoint_url=s.minio_endpoint,
            aws_access_key_id=s.minio_root_user,
            aws_secret_access_key=s.minio_root_password,
            region_name=_DEFAULT_REGION,
            config=Config(
                signature_version="s3v4",
                # MinIO is addressed by host:port, so virtual-host addressing
                # would resolve "pubg-telemetry.localhost:9000" and fail.
                s3={"addressing_style": "path"},
                max_pool_connections=max_pool_connections,
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=120,  # generous: a multi-MB telemetry GET over a slow link
            ),
        )

    # --- bucket bootstrap ---------------------------------------------------
    async def ensure_bucket(self) -> None:
        """Create the bucket if absent. Cheap no-op after the first call."""
        if self._bucket_ready:
            return
        async with self._bucket_lock:
            if self._bucket_ready:
                return
            await asyncio.to_thread(self._ensure_bucket_sync)
            self._bucket_ready = True

    def _ensure_bucket_sync(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return
        except ClientError as exc:
            if _error_code(exc) not in _NOT_FOUND_CODES:
                raise StorageError(f"cannot reach bucket {self._bucket!r}: {exc}") from exc
        try:
            # No CreateBucketConfiguration: real S3 rejects an explicit
            # LocationConstraint of us-east-1, and MinIO ignores it anyway.
            self._client.create_bucket(Bucket=self._bucket)
        except ClientError as exc:
            # Another worker won the race; that is success, not failure.
            if _error_code(exc) not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise StorageError(f"cannot create bucket {self._bucket!r}: {exc}") from exc

    # --- primitives ---------------------------------------------------------
    async def put(self, key: str, data: bytes, content_type: str = GZIP_CONTENT_TYPE) -> None:
        validate_key(key)
        await self.ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        validate_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            # Body.read() is itself blocking network IO, so it MUST happen here
            # in the worker thread. Returning the StreamingBody and reading it
            # on the event loop is the classic version of this bug.
            body: bytes = resp["Body"].read()
            return body
        except ClientError as exc:
            if _error_code(exc) in _NOT_FOUND_CODES:
                raise ObjectNotFoundError(key) from exc
            raise StorageError(f"get {key!r} failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        validate_key(key)
        return await asyncio.to_thread(self._exists_sync, key)

    def _exists_sync(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if _error_code(exc) in _NOT_FOUND_CODES:
                return False
            raise StorageError(f"exists {key!r} failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        validate_key(key)
        # S3 DELETE is already idempotent — it 204s on a missing key.
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def size(self, key: str) -> int:
        validate_key(key)
        return await asyncio.to_thread(self._size_sync, key)

    def _size_sync(self, key: str) -> int:
        try:
            resp = self._client.head_object(Bucket=self._bucket, Key=key)
            return int(resp["ContentLength"])
        except ClientError as exc:
            if _error_code(exc) in _NOT_FOUND_CODES:
                raise ObjectNotFoundError(key) from exc
            raise StorageError(f"size {key!r} failed: {exc}") from exc

    async def iter_keys(self, prefix: str) -> AsyncIterator[str]:
        await self.ensure_bucket()
        pages = iter(
            self._client.get_paginator("list_objects_v2").paginate(
                Bucket=self._bucket, Prefix=prefix
            )
        )
        while True:
            # `next(it, None)` rather than `next(it)`: a StopIteration raised
            # inside a thread/coroutine boundary becomes an opaque RuntimeError.
            # One thread hop per 1000-key page, not per key.
            page = await asyncio.to_thread(next, pages, None)
            if page is None:
                return
            for obj in page.get("Contents", []):
                yield str(obj["Key"])

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)
