from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import Storage, StorageError
from app.storage.local import LocalStorage, UploadTooLarge


@lru_cache
def get_storage() -> Storage:
    return LocalStorage(get_settings().objects_dir)


def raw_key(workspace_id: object, dataset_id: object, version_id: object, ext: str) -> str:
    return f"raw/{workspace_id}/{dataset_id}/{version_id}/original.{ext}"


def processed_key(workspace_id: object, dataset_id: object, version_id: object) -> str:
    return f"processed/{workspace_id}/{dataset_id}/{version_id}/data.parquet"


def dataset_prefixes(workspace_id: object, dataset_id: object) -> list[str]:
    return [f"raw/{workspace_id}/{dataset_id}", f"processed/{workspace_id}/{dataset_id}"]


__all__ = [
    "LocalStorage",
    "Storage",
    "StorageError",
    "UploadTooLarge",
    "dataset_prefixes",
    "get_storage",
    "processed_key",
    "raw_key",
]
