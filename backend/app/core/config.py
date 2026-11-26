"""Application settings, loaded from environment variables prefixed with ``FACET_``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Defaults that appear in this repository; never acceptable outside local development.
_DEV_SECRETS = frozenset(
    {"facet-dev-token", "facet-dev-secret-change-me", "change-me-in-production"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FACET_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://facet:facet@localhost:5432/facet"
    data_dir: Path = Path("./data")

    # Auth: a development token is seeded so the local UI works without a login flow.
    dev_token: str = "facet-dev-token"  # noqa: S105 - local development only
    seed_dev_user: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Upload limits
    max_upload_bytes: int = 2 * 1024**3  # 2 GiB
    upload_chunk_bytes: int = 1024**2

    # Query sandbox limits
    query_timeout_s: float = 30.0
    query_memory_limit: str = "1GB"
    query_threads: int = 2
    query_max_rows: int = 10_000
    query_page_size_max: int = 1_000
    query_workers: int = 4  # number of sandbox processes == max concurrent queries

    # Ingestion worker
    ingest_memory_limit: str = "2GB"
    ingest_threads: int = 4
    job_lease_s: int = 60
    job_max_attempts: int = 3
    worker_poll_interval_s: float = 0.5

    # Profiling: sample tables larger than this many rows for expensive metrics
    profile_sample_threshold: int = 5_000_000
    profile_sample_rows: int = 1_000_000

    # Export limits
    export_max_rows: int = 5_000_000
    export_link_ttl_s: int = 600
    # Signs short-lived download links. Override in any shared deployment.
    secret_key: str = "facet-dev-secret-change-me"  # noqa: S105 - local development only
    # Export files are deleted this long after creation; links expire much sooner.
    export_retention_s: int = 24 * 3600
    export_sweep_interval_s: float = 300.0

    @model_validator(mode="after")
    def _no_dev_secrets_outside_development(self) -> "Settings":
        """Refuse to boot a non-development deployment with the published defaults."""
        if self.env == "development":
            return self
        problems = []
        if self.secret_key in _DEV_SECRETS:
            problems.append("FACET_SECRET_KEY is a published default")
        if self.seed_dev_user and self.dev_token in _DEV_SECRETS:
            problems.append(
                "FACET_DEV_TOKEN is a published default (or set FACET_SEED_DEV_USER=false)"
            )
        if problems:
            raise ValueError(f"Unsafe settings for FACET_ENV={self.env!r}: " + "; ".join(problems))
        return self

    @property
    def objects_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
