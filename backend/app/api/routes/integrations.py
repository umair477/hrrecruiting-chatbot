from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.database import get_session
from app.deps import require_roles
from app.models import User, UserRole
from app.schemas import HRISSyncResponse, MessagingPlatformStatus
from app.services.hris import sync_leave_balance
from app.services.messaging import list_messaging_platforms

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/messaging/platforms", response_model=list[MessagingPlatformStatus])
def messaging_platforms(
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[MessagingPlatformStatus]:
    return [MessagingPlatformStatus(**platform) for platform in list_messaging_platforms()]


@router.post("/hris/{provider}/sync/{employee_id}", response_model=HRISSyncResponse)
def sync_hris_provider(
    provider: str,
    employee_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> HRISSyncResponse:
    try:
        result = sync_leave_balance(provider, employee_id, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return HRISSyncResponse(**result)

