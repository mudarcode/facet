"""Non-development deployments must not boot with secrets published in this repo."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_development_allows_defaults():
    assert Settings(env="development").secret_key


@pytest.mark.parametrize("env", ["production", "staging"])
def test_production_rejects_default_secret_key(env):
    with pytest.raises(ValidationError, match="FACET_SECRET_KEY"):
        Settings(env=env, seed_dev_user=False)


def test_production_rejects_default_dev_token_when_seeding():
    with pytest.raises(ValidationError, match="FACET_DEV_TOKEN"):
        Settings(env="production", secret_key="x" * 40)


def test_production_with_real_secrets_is_accepted():
    s = Settings(env="production", secret_key="x" * 40, dev_token="y" * 40)
    assert s.env == "production"
    assert Settings(env="production", secret_key="x" * 40, seed_dev_user=False)
