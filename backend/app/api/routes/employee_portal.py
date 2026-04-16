from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.deps import require_roles
from app.models import Employee, LeaveRequest, User, UserRole
from app.schemas import (
    EmployeeLeaveCreateRequest,
    EmployeeLeaveQuotaRead,
    EmployeeLeaveRead,
    LeaveChatHistoryItem,
    LeaveChatRequest,
    LeaveChatResponse,
)
from app.services.employee_portal import (
    coerce_leave_type,
    get_employee_leave_quota_summary,
    list_employee_leave_history,
    run_employee_leave_chat_turn,
    submit_employee_leave_request,
)


router = APIRouter(tags=["employee-portal"])


def _require_current_employee(current_user: User, session: Session) -> Employee:
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not linked to this user.")
    employee = session.get(Employee, current_user.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee account is inactive.")
    return employee


def _to_employee_leave_read(leave_request: LeaveRequest) -> EmployeeLeaveRead:
    return EmployeeLeaveRead(
        leave_id=int(leave_request.id),
        leave_type=leave_request.leave_type,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        total_days=int(leave_request.total_days),
        reason=leave_request.reason,
        status=leave_request.status,
        hr_note=leave_request.hr_note,
        submitted_at=leave_request.submitted_at,
    )


@router.post("/chat/leave", response_model=LeaveChatResponse)
def leave_chat(
    payload: LeaveChatRequest,
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> LeaveChatResponse:
    employee = _require_current_employee(current_user, session)
    try:
        reply, conversation_history = run_employee_leave_chat_turn(
            session=session,
            employee=employee,
            message=payload.message,
            conversation_history=[item.model_dump() for item in payload.conversation_history],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return LeaveChatResponse(
        reply=reply,
        conversation_history=[
            LeaveChatHistoryItem(role=item["role"], content=item["content"]) for item in conversation_history
        ],
    )


@router.post("/leaves", response_model=EmployeeLeaveRead, status_code=status.HTTP_201_CREATED)
def submit_leave_request(
    payload: EmployeeLeaveCreateRequest,
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> EmployeeLeaveRead:
    employee = _require_current_employee(current_user, session)
    try:
        leave_request = submit_employee_leave_request(
            session=session,
            employee_id=int(employee.id),
            leave_type=coerce_leave_type(payload.leave_type),
            start_date=payload.start_date,
            end_date=payload.end_date,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_employee_leave_read(leave_request)


@router.get("/leaves/my", response_model=list[EmployeeLeaveRead])
def list_my_leaves(
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> list[EmployeeLeaveRead]:
    employee = _require_current_employee(current_user, session)
    leaves = list_employee_leave_history(session, int(employee.id))
    return [_to_employee_leave_read(leave_request) for leave_request in leaves]


@router.get("/leaves/quota/my", response_model=EmployeeLeaveQuotaRead)
def my_leave_quota(
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> EmployeeLeaveQuotaRead:
    employee = _require_current_employee(current_user, session)
    summary = get_employee_leave_quota_summary(session, int(employee.id))
    return EmployeeLeaveQuotaRead(
        annual_total=summary["annual_total"],
        annual_remaining=summary["annual_remaining"],
        sick_total=summary["sick_total"],
        sick_remaining=summary["sick_remaining"],
        casual_total=summary["casual_total"],
        casual_remaining=summary["casual_remaining"],
        unpaid_used=summary["unpaid_used"],
    )
