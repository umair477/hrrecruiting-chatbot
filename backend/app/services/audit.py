from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import AuditEvent


def log_audit_event(
    *,
    session: Session,
    actor_type: str,
    actor_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
