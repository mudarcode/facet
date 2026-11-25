import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.analytics.charts import ChartSpec
from app.analytics.transforms import Condition
from app.schemas.common import ApiModel
from app.schemas.datasets import ResultColumn


class ChartSource(BaseModel):
    dataset_id: uuid.UUID | None = None
    saved_query_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ChartSource":
        if (self.dataset_id is None) == (self.saved_query_id is None):
            raise ValueError("set exactly one of dataset_id or saved_query_id")
        return self


class ChartIn(ChartSource):
    name: str = Field(min_length=1, max_length=200)
    spec: ChartSpec


class ChartPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    spec: ChartSpec | None = None


class ChartOut(ApiModel):
    id: uuid.UUID
    name: str
    dataset_id: uuid.UUID | None
    saved_query_id: uuid.UUID | None
    spec: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    source_name: str | None = None


class ChartDataIn(ChartSource):
    spec: ChartSpec
    filters: list[Condition] = Field(default_factory=list)


class ChartDataFilters(BaseModel):
    filters: list[Condition] = Field(default_factory=list, max_length=20)


class ChartDataOut(BaseModel):
    columns: list[ResultColumn]
    rows: list[list[Any]]
    meta: dict[str, Any]
    sql: str
    engine_ms: float
    total_ms: float


class SourceColumnsOut(BaseModel):
    columns: list[ResultColumn]


class LayoutItem(BaseModel):
    i: str = Field(min_length=1, max_length=64)
    chart_id: uuid.UUID
    x: int = Field(ge=0, le=48)
    y: int = Field(ge=0, le=10_000)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=2, le=40)


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    layout: list[LayoutItem] = Field(default_factory=list, max_length=60)
    filters: list[Condition] = Field(default_factory=list, max_length=20)


class DashboardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    layout: list[LayoutItem] | None = Field(default=None, max_length=60)
    filters: list[Condition] | None = Field(default=None, max_length=20)


class DashboardOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str
    layout: list[dict[str, Any]]
    filters: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ExportSource(BaseModel):
    kind: Literal["query", "dataset", "chart"]
    sql: str | None = Field(default=None, max_length=100_000)
    dataset_id: uuid.UUID | None = None
    chart_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _matches_kind(self) -> "ExportSource":
        need = {"query": self.sql, "dataset": self.dataset_id, "chart": self.chart_id}[self.kind]
        if need is None:
            raise ValueError(f"{self.kind} export needs its source field")
        return self


class ExportIn(BaseModel):
    source: ExportSource
    format: Literal["csv", "parquet"] = "csv"


class ExportOut(ApiModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    status: str
    format: str
    filename: str
    row_count: int | None
    bytes: int | None
    error: str | None
    created_at: datetime
    download_url: str | None = None
