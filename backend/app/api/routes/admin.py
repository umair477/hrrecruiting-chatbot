from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import Employee, LeaveRequest, LeaveStatus, User, UserRole
from backend.app.schemas import AdminUserRead, LeaveRequestRead, PromoteCandidateRequest

router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.get("/all-leaves", response_model=list[LeaveRequestRead])
def list_all_leaves(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[LeaveRequestRead]:
    leave_requests = session.exec(select(LeaveRequest).order_by(LeaveRequest.created_at.desc())).all()
    employees = {employee.id: employee for employee in session.exec(select(Employee)).all()}
    return [
        _to_leave_read(leave_request, employees[leave_request.employee_id])
        for leave_request in leave_requests
        if leave_request.employee_id in employees
    ]


@router.get("/users", response_model=list[AdminUserRead])
def list_users(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminUserRead]:
    users = session.exec(select(User).order_by(User.created_at.asc())).all()
    return [AdminUserRead.model_validate(user) for user in users]


@router.post("/users/{user_id}/promote", response_model=AdminUserRead)
def promote_candidate_to_employee(
    user_id: int,
    payload: PromoteCandidateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminUserRead:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.role != UserRole.CANDIDATE:
        raise HTTPException(status_code=400, detail="Only candidate users can be promoted.")

    employee = Employee(
        name=user.full_name,
        department=payload.department,
        annual_allowance=payload.annual_allowance,
        leave_balance=payload.annual_allowance,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)

    user.role = UserRole.EMPLOYEE
    user.employee_id = employee.id
    session.add(user)
    session.commit()
    session.refresh(user)
    return AdminUserRead.model_validate(user)


@router.post("/leave/{leave_request_id}/approve", response_model=LeaveRequestRead)
def approve_leave(
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
