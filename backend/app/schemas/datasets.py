import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel


class ColumnSchema(BaseModel):
    name: str
    type: str
    nullable: bool = True


class DatasetVersionOut(ApiModel):
    id: uuid.UUID
    version: int
    status: str
    source_format: str
    original_filename: str
    raw_bytes: int | None
    processed_bytes: int | None
    row_count: int | None
    column_count: int | None
    columns: list[ColumnSchema] | None = Field(default=None, validation_alias="schema_json")
    ingest_options: dict[str, Any]
    ingest_report: dict[str, Any]
    error: str | None
    created_at: datetime


class DatasetOut(ApiModel):
    id: uuid.UUID
    name: str
    sql_name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    row_count: int | None = None
    column_count: int | None = None
    processed_bytes: int | None = None
    source_format: str | None = None
    current_version: DatasetVersionOut | None = None
    latest_job_id: uuid.UUID | None = None
    error: str | None = None


class DatasetCreated(BaseModel):
    dataset: DatasetOut
    job_id: uuid.UUID


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sql_name: str | None = Field(default=None, pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    description: str | None = Field(default=None, max_length=5000)


class IngestOptionsIn(BaseModel):
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    header: bool | None = None
    encoding: Literal["auto", "utf-8", "utf-16", "latin-1"] = "auto"
    quote: str | None = Field(default=None, min_length=1, max_length=1)
    skip_rows: int = Field(default=0, ge=0, le=1000)
    max_reject_ratio: float = Field(default=0.1, ge=0, le=1)
    type_overrides: dict[str, str] = Field(default_factory=dict)


class ReprocessIn(BaseModel):
    """Re-ingest the original file with corrected options/types as a new version."""

    options: IngestOptionsIn


class ResultColumn(BaseModel):
    name: str
    type: str


class PreviewOut(BaseModel):
    columns: list[ResultColumn]
    rows: list[list[Any]]
    total_rows: int
    offset: int
    limit: int
