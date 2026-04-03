from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import Employee, LeaveRequest, LeaveStatus, User, UserRole
from backend.app.schemas import LeaveBalanceRead, LeaveRequestRead, LeaveRequestStatusUpdate
from backend.app.services.hris import sync_leave_balance
from backend.app.services.leave import get_leave_balance_summary, resolve_leave_history_scope

router = APIRouter(prefix="/leave", tags=["leave"])


def _to_leave_read(leave_request: LeaveRequest, employee: Employee) -> LeaveRequestRead:
    return LeaveRequestRead(
        id=leave_request.id,
        employee_id=leave_request.employee_id,
        employee_name=employee.name,
        department=employee.department,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        reason=leave_request.reason,
        status=leave_request.status,
        handover_contact=leave_request.handover_contact,
        handover_notes=leave_request.handover_notes,
        urgency_level=leave_request.urgency_level,
        privacy_flagged=leave_request.privacy_flagged,
        created_at=leave_request.created_at,
    )


@router.get("/requests", response_model=list[LeaveRequestRead])
@router.get("/admin/all-leaves", response_model=list[LeaveRequestRead])
def list_leave_requests(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[LeaveRequestRead]:
    leave_requests = session.exec(select(LeaveRequest).order_by(LeaveRequest.created_at.desc())).all()
    employees = {
        employee.id: employee for employee in session.exec(select(Employee)).all()
    }
    return [
        _to_leave_read(leave_request, employees[leave_request.employee_id])
        for leave_request in leave_requests
        if leave_request.employee_id in employees
    ]


@router.patch("/requests/{leave_request_id}", response_model=LeaveRequestRead)
def update_leave_request_status(
    leave_request_id: int,
    payload: LeaveRequestStatusUpdate,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> LeaveRequestRead:
    leave_request = session.get(LeaveRequest, leave_request_id)
    if leave_request is None:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    leave_request.status = payload.status
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    employee = session.get(Employee, leave_request.employee_id)
    return _to_leave_read(leave_request, employee)


@router.post("/approve/{leave_request_id}", response_model=LeaveRequestRead)
def approve_leave_request(
    leave_request_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> LeaveRequestRead:
    leave_request = session.get(LeaveRequest, leave_request_id)
    if leave_request is None:
        raise HTTPException(status_code=404, detail="Leave request not found.")

    leave_request.status = LeaveStatus.APPROVED
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    employee = session.get(Employee, leave_request.employee_id)
    return _to_leave_read(leave_request, employee)


@router.get("/history", response_model=list[LeaveRequestRead])
def leave_history(
    employee_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> list[LeaveRequestRead]:
    leave_requests = resolve_leave_history_scope(current_user, session, employee_id=employee_id)
    employees = {
        employee.id: employee for employee in session.exec(select(Employee)).all()
    }
    return [
        _to_leave_read(leave_request, employees[leave_request.employee_id])
        for leave_request in leave_requests
        if leave_request.employee_id in employees
    ]


@router.get("/balance", response_model=LeaveBalanceRead)
def my_leave_balance(
    employee_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> LeaveBalanceRead:
    target_employee_id = employee_id
    if current_user.role != UserRole.ADMIN:
        if current_user.employee_id is None:
            raise HTTPException(status_code=404, detail="Current user is not linked to an employee profile.")
        target_employee_id = current_user.employee_id

    if target_employee_id is None:
        raise HTTPException(status_code=400, detail="employee_id is required for admin balance lookups.")

    employee = session.get(Employee, target_employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found.")

    balance = get_leave_balance_summary(session, employee)
    return LeaveBalanceRead(**balance)


@router.get("/balance/me", response_model=LeaveBalanceRead)
def my_leave_balance_legacy(
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> LeaveBalanceRead:
    if current_user.employee_id is None:
        raise HTTPException(status_code=404, detail="Current user is not linked to an employee profile.")
    employee = session.get(Employee, current_user.employee_id)
    balance = get_leave_balance_summary(session, employee)
    return LeaveBalanceRead(**balance)


@router.post("/balance/sync/{provider}/{employee_id}", response_model=LeaveBalanceRead)
def sync_balance(
    provider: str,
    employee_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> LeaveBalanceRead:
    result = sync_leave_balance(provider, employee_id, session)
    return LeaveBalanceRead(
        employee_id=result["employee_id"],
        total=result["leave_balance"],
        used=0,
        remaining=result["leave_balance"],
        provider=result["provider"],
    )
