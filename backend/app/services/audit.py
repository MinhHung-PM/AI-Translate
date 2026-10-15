from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit event in the caller's transaction.

    ``details`` must contain only identifiers, counts and enum values — never
    secrets or transcript text.
    """
    db.add(
        AuditEvent(
            actor_user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            project_id=project_id,
            details=details or {},
            ip_address=ip,
        )
    )
