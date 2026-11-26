"""Storage containment, token storage and unauthenticated access."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import ApiToken
from app.storage.base import StorageError
from app.storage.local import LocalStorage


@pytest.mark.parametrize("key", ["../outside", "a/../../outside", "/etc/passwd", "raw/../../x"])
def test_storage_keys_cannot_escape_root(tmp_path, key):
    store = LocalStorage(tmp_path / "root")
    with pytest.raises(StorageError):
        store.local_path(key)


def test_storage_keys_inside_root_resolve(tmp_path):
    store = LocalStorage(tmp_path)
    assert store.local_path("raw/a/b.csv") == (tmp_path / "raw/a/b.csv").resolve()


def test_tokens_are_stored_only_as_hashes(client):
    token = get_settings().dev_token
    with get_sessionmaker()() as db:
        hashes = db.scalars(select(ApiToken.token_hash)).all()
    assert hashes and token not in hashes
    assert all(len(h) == 64 for h in hashes)


@pytest.mark.parametrize(
    "path", ["/api/v1/datasets", "/api/v1/charts", "/api/v1/dashboards", "/api/v1/activity"]
)
@pytest.mark.parametrize("auth", [None, "Bearer wrong", "Basic abc"])
def test_requests_without_a_valid_token_get_401(client, path, auth):
    headers = {"Authorization": auth} if auth else {}
    assert client.get(path, headers=headers).status_code == 401
