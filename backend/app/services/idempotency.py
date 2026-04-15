from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.app.models import IdempotencyRecord


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request payload."""


def payload_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(normalized.encode("utf-8")).hexdigest()


def fetch_record(*, session: Session, idempotency_key: str) -> IdempotencyRecord | None:
    return session.exec(
        select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == idempotency_key)
    ).first()


def save_record(
    *,
    session: Session,
    idempotency_key: str,
    endpoint: str,
    request_hash: str,
    response_payload: dict[str, Any],
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        endpoint=endpoint,
        request_hash=request_hash,
        response_payload=response_payload,
    )
    session.add(record)
    try:
        session.commit()
        session.refresh(record)
        return record
    except IntegrityError:
        session.rollback()
        existing = fetch_record(session=session, idempotency_key=idempotency_key)
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError("Idempotency key reuse with different payload.")
        return existing
