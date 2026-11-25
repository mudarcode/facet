"""Bearer-token authentication and workspace resolution.

Facet ships with a single seeded development user so the local app works out of
the box. The data model and every service call are nevertheless scoped by
workspace, and tests exercise two users to prove isolation. A production
deployment would swap ``get_principal`` for real session/OIDC auth.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Unauthorized
from app.models import ApiToken, User, Workspace


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return "fct_" + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    workspace_id: uuid.UUID


def get_principal(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    row = db.execute(
        select(User.id, Workspace.id)
        .join(ApiToken, ApiToken.user_id == User.id)
        .join(Workspace, Workspace.owner_id == User.id)
        .where(ApiToken.token_hash == hash_token(token))
        .order_by(Workspace.created_at)
        .limit(1)
    ).first()
    if row is None:
        raise Unauthorized("Invalid token.")
    return Principal(user_id=row[0], workspace_id=row[1])
