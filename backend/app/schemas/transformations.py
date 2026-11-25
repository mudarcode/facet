import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.analytics.transforms import Step
from app.schemas.common import ApiModel
from app.schemas.datasets import ResultColumn


class TransformPreviewIn(BaseModel):
    dataset_id: uuid.UUID
    steps: list[Step] = Field(default_factory=list, max_length=50)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class TransformPreviewOut(BaseModel):
    sql: str
    columns: list[ResultColumn]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool
    engine_ms: float


class TransformationIn(BaseModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    steps: list[Step] = Field(default_factory=list, max_length=50)


class TransformationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    steps: list[Step] | None = Field(default=None, max_length=50)


class TransformationOut(ApiModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    steps: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    sql: str | None = None
    output_dataset_id: uuid.UUID | None = None


class MaterializeIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class MaterializeOut(BaseModel):
    dataset_id: uuid.UUID
    job_id: uuid.UUID
