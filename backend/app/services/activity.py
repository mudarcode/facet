import uuid

from sqlalchemy.orm import Session

from app.models import ActivityEvent


def record(
    db: Session,
    workspace_id: uuid.UUID,
    kind: str,
    subject_type: str,
    subject_id: uuid.UUID | None,
    summary: str,
) -> None:
    db.add(
        ActivityEvent(
            workspace_id=workspace_id,
            kind=kind,
            subject_type=subject_type,
            subject_id=subject_id,
            summary=summary[:500],
        )
    )
