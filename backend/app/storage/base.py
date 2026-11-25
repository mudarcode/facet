"""Object storage abstraction.

Keys are ``/``-separated relative paths such as ``processed/<ws>/<ds>/<ver>/data.parquet``.
DuckDB needs a filesystem path to read Parquet efficiently, so backends expose
``local_path``; an S3 backend would return ``s3://`` URLs and the sandbox would
allow-list those instead.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO


class StorageError(Exception):
    pass


class Storage(ABC):
    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Filesystem path for ``key`` (may not exist yet)."""

    @abstractmethod
    async def write_stream(
        self, key: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> tuple[int, str]:
        """Stream chunks into ``key``. Returns (bytes_written, sha256). Aborts past max_bytes."""

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def commit_tmp(self, tmp_key: str, final_key: str) -> None:
        """Atomically move a fully written temporary object into place."""

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix``. Returns number of files removed."""
