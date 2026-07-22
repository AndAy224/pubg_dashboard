"""Local-disk backend, used when `settings.storage_backend == "filesystem"`.

Keys map 1:1 onto a nested path under `settings.telemetry_dir`, so
`telemetry/steam/2026/07/<match_id>.json.gz` becomes
`data/telemetry/telemetry/steam/2026/07/<match_id>.json.gz`. The doubled
"telemetry" is intentional: the key namespace is shared with the S3 backend and
also holds `replay/...`, so the root cannot absorb the first component.

Everything here is blocking file IO pushed onto a worker thread, same as the
S3 backend. Reads are only a couple of MB, but they are `fsync`-ing writes and
cold-cache reads off spinning storage — not event-loop work.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
from collections.abc import AsyncIterator

from pubg_dashboard.config import Settings, get_settings
from pubg_dashboard.storage.base import (
    GZIP_CONTENT_TYPE,
    ObjectNotFoundError,
    Storage,
    StorageError,
    validate_key,
)

__all__ = ["FilesystemStorage"]


class FilesystemStorage(Storage):
    def __init__(self, settings: Settings | None = None, root: pathlib.Path | None = None) -> None:
        # An explicit root short-circuits settings entirely, so tests never have
        # to construct (or monkeypatch) a Settings just to get a temp dir.
        if root is None:
            root = (settings or get_settings()).telemetry_dir
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> pathlib.Path:
        validate_key(key)
        path = (self._root / key).resolve()
        # Belt-and-braces: validate_key already blocks "..", but symlinks inside
        # the tree can still redirect outside it.
        if not path.is_relative_to(self._root):
            raise StorageError(f"key escapes storage root: {key!r}")
        return path

    # --- primitives ---------------------------------------------------------
    async def put(self, key: str, data: bytes, content_type: str = GZIP_CONTENT_TYPE) -> None:
        # content_type has no on-disk representation; the extension carries it.
        await asyncio.to_thread(self._put_sync, self._path(key), data)

    @staticmethod
    def _put_sync(path: pathlib.Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename. A crash mid-download must not leave a truncated
        # .json.gz behind, because `exists()` would then report the match as
        # already fetched and it would never be re-downloaded — and PUBG drops
        # telemetry after 14 days, so that loss is permanent.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)  # atomic on both POSIX and Windows
        except BaseException:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
            raise

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc
        except OSError as exc:
            raise StorageError(f"get {key!r} failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete_sync, self._path(key))

    def _delete_sync(self, path: pathlib.Path) -> None:
        path.unlink(missing_ok=True)
        # Prune now-empty date partitions so a retention sweep does not leave
        # thousands of empty yyyy/mm directories behind. S3 has no directories,
        # so this only exists to keep the two backends looking alike.
        parent = path.parent
        while parent != self._root and parent.is_relative_to(self._root):
            try:
                parent.rmdir()
            except OSError:
                return  # not empty (or in use) — stop climbing
            parent = parent.parent

    async def size(self, key: str) -> int:
        path = self._path(key)
        try:
            stat = await asyncio.to_thread(path.stat)
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(key) from exc
        return stat.st_size

    async def iter_keys(self, prefix: str) -> AsyncIterator[str]:
        for key in await asyncio.to_thread(self._list_sync, prefix):
            yield key

    def _list_sync(self, prefix: str) -> list[str]:
        # A prefix need not be a directory ("telemetry/steam/2026/0" is legal),
        # so walk the deepest directory that certainly contains every match and
        # filter afterwards.
        if not prefix or prefix.endswith("/"):
            search_root = self._root / prefix
        else:
            search_root = (self._root / prefix).parent
        if not search_root.is_dir():
            return []
        keys: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(search_root):
            base = pathlib.Path(dirpath)
            for name in filenames:
                if name.startswith(".tmp-"):
                    continue  # an in-flight write is not an object yet
                # Keys are always "/"-separated regardless of host OS.
                key = (base / name).relative_to(self._root).as_posix()
                if key.startswith(prefix):
                    keys.append(key)
        return keys
