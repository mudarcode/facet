import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel
from app.schemas.datasets import ResultColumn


class QueryExecuteIn(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)
    saved_query_id: uuid.UUID | None = None
    record_history: bool = True


class QueryResultOut(BaseModel):
    columns: list[ResultColumn]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool = Field(description="True when the full result exceeded the row cap")
    max_rows: int
    offset: int
    limit: int
    engine_ms: float = Field(description="Time spent inside DuckDB")
    total_ms: float = Field(description="Server-side time including validation and IPC")
    datasets: list[str]
    run_id: uuid.UUID | None = None


class ExplainOut(BaseModel):
    plan: str


class SavedQueryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sql: str = Field(min_length=1, max_length=100_000)
    description: str = Field(default="", max_length=5000)


class SavedQueryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sql: str | None = Field(default=None, min_length=1, max_length=100_000)
    description: str | None = Field(default=None, max_length=5000)


class SavedQueryOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    sql: str
    created_at: datetime
    updated_at: datetime


class QueryRunOut(ApiModel):
    id: uuid.UUID
    sql: str
    status: str
    row_count: int | None
    engine_ms: float | None
    total_ms: float | None
    error: str | None
    saved_query_id: uuid.UUID | None
    created_at: datetime
