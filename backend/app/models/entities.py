"""PostgreSQL metadata model. Analytical data itself lives in Parquet, never in these tables."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))


class ApiToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "api_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(100), default="default")


class Workspace(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))


class Dataset(IdMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("workspace_id", "sql_name", name="uq_datasets_ws_sql_name"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Identifier users write in SQL (``SELECT * FROM sales``). Unique per workspace.
    sql_name: Mapped[str] = mapped_column(String(63))
    description: Mapped[str] = mapped_column(Text, default="")
    # pending | processing | ready | failed | deleting
    status: Mapped[str] = mapped_column(String(20), default="pending")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    # Set when created from a transformation of another dataset.
    source_transformation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="dataset",
        foreign_keys="DatasetVersion.dataset_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    current_version: Mapped["DatasetVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class DatasetVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    source_format: Mapped[str] = mapped_column(String(20))  # csv | parquet | derived
    original_filename: Mapped[str] = mapped_column(String(500), default="")
    raw_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    processed_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{name, type, nullable, original_name}]
    schema_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Options used for ingestion (delimiter, encoding, header, type overrides…)
    ingest_options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Warnings collected during ingestion, e.g. rejected rows, renamed headers.
    ingest_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="versions", foreign_keys=[dataset_id])


class Job(IdMixin, TimestampMixin, Base):
    """A unit of background work. Claimed with ``FOR UPDATE SKIP LOCKED`` by workers."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50))  # ingest | profile | export | materialize
    # queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    progress: Mapped[float] = mapped_column(default=0.0)
    message: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedQuery(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_queries"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str] = mapped_column(Text)


class QueryRun(IdMixin, TimestampMixin, Base):
    """Query history: one row per execution attempt (successful or not)."""

    __tablename__ = "query_runs"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    saved_query_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="SET NULL"), nullable=True
    )
    sql: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # succeeded | failed | rejected | timeout
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    engine_ms: Mapped[float | None] = mapped_column(nullable=True)
    total_ms: Mapped[float | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Transformation(IdMixin, TimestampMixin, Base):
    __tablename__ = "transformations"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Ordered list of typed steps; see app.analytics.transforms.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Chart(IdMixin, TimestampMixin, Base):
    __tablename__ = "charts"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    # Data source: exactly one of dataset_id / saved_query_id is set.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True
    )
    saved_query_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("saved_queries.id", ondelete="CASCADE"), nullable=True
    )
    # {type, x, y:[{field, agg}], group_by, filters, options}
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Dashboard(IdMixin, TimestampMixin, Base):
    __tablename__ = "dashboards"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # [{id, chart_id, x, y, w, h}]
    layout: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class Export(IdMixin, TimestampMixin, Base):
    __tablename__ = "exports"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[dict[str, Any]] = mapped_column(JSONB)  # {kind: query|dataset|chart, ...}
    format: Mapped[str] = mapped_column(String(10))  # csv | parquet
    status: Mapped[str] = mapped_column(String(20), default="queued")
    storage_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ActivityEvent(IdMixin, TimestampMixin, Base):
    """Lightweight audit/recent-activity feed for the workspace home page."""

    __tablename__ = "activity_events"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    summary: Mapped[str] = mapped_column(String(500))
