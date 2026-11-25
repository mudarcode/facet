import hashlib
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

from app.storage.base import Storage, StorageError


class UploadTooLarge(StorageError):
    pass


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def local_path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError(f"key escapes storage root: {key!r}")
        return path

    async def write_stream(
        self, key: str, chunks: AsyncIterator[bytes], *, max_bytes: int
    ) -> tuple[int, str]:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        try:
            with path.open("wb") as fh:
                async for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise UploadTooLarge(f"upload exceeds limit of {max_bytes} bytes")
                    digest.update(chunk)
                    fh.write(chunk)
        except BaseException:
            # Interrupted or rejected uploads never leave partial objects behind.
            path.unlink(missing_ok=True)
            raise
        return written, digest.hexdigest()

    def open(self, key: str) -> BinaryIO:
        return self.local_path(key).open("rb")

    def exists(self, key: str) -> bool:
        return self.local_path(key).exists()

    def size(self, key: str) -> int:
        return self.local_path(key).stat().st_size

    def commit_tmp(self, tmp_key: str, final_key: str) -> None:
        src, dst = self.local_path(tmp_key), self.local_path(final_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)  # atomic on POSIX within one filesystem

    def delete(self, key: str) -> None:
        self.local_path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> int:
        path = self.local_path(prefix)
        if not path.exists():
            return 0
        if path.is_file():
            path.unlink()
            return 1
        count = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path)
        return count
