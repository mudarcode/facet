from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_token
from app.models import ApiToken, User, Workspace


def ensure_user(db: Session, *, email: str, name: str, token: str) -> tuple[User, Workspace]:
    """Idempotently create a user with one workspace and the given API token."""
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=name)
        db.add(user)
        db.flush()
    ws = db.scalar(select(Workspace).where(Workspace.owner_id == user.id))
    if ws is None:
        ws = Workspace(owner_id=user.id, name=f"{name}'s workspace")
        db.add(ws)
    th = hash_token(token)
    if db.scalar(select(ApiToken).where(ApiToken.token_hash == th)) is None:
        db.add(ApiToken(user_id=user.id, token_hash=th, label="dev"))
    db.commit()
    return user, ws
