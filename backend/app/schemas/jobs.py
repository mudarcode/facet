import uuid
from datetime import datetime
from typing import Any

from app.schemas.common import ApiModel


class JobOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    progress: float
    message: str
    error: str | None
    attempts: int
    result: dict[str, Any] | None
    payload: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
