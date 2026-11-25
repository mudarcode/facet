from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.analytics.sandbox import SandboxPool
from app.core.db import get_db
from app.core.security import Principal, get_principal

DB = Annotated[Session, Depends(get_db)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def get_pool(request: Request) -> SandboxPool:
    return request.app.state.sandbox  # type: ignore[no-any-return]


Pool = Annotated[SandboxPool, Depends(get_pool)]
