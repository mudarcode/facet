"""Application settings, loaded from environment variables prefixed with ``FACET_``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FACET_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+psycopg://facet:facet@localhost:5432/facet"
    data_dir: Path = Path("./data")

    # Auth: a development token is seeded so the local UI works without a login flow.
    dev_token: str = "facet-dev-token"
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

    @property
    def objects_dir(self) -> Path:
        return self.data_dir / "objects"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
