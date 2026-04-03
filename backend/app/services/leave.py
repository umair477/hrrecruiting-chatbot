from __future__ import annotations

from sqlmodel import Session, select

from backend.app.models import Employee, LeaveRequest, LeaveStatus, User, UserRole


def calculate_leave_days(leave_request: LeaveRequest) -> int:
    return (leave_request.end_date - leave_request.start_date).days + 1


def get_approved_leave_days(session: Session, employee_id: int) -> int:
    approved_requests = session.exec(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
        )
    ).all()
    return sum(calculate_leave_days(request) for request in approved_requests)


def get_leave_balance_summary(session: Session, employee: Employee) -> dict[str, float | int | str]:
    used = float(get_approved_leave_days(session, employee.id))
    total = float(employee.annual_allowance)
    remaining = max(total - used, 0.0)
    return {
        "employee_id": int(employee.id),
        "total": total,
        "used": used,
        "remaining": remaining,
        "provider": "dynamic_approved_leave_requests",
    }


def resolve_leave_history_scope(
    current_user: User,
    session: Session,
    *,
    employee_id: int | None = None,
) -> list[LeaveRequest]:
    if current_user.role == UserRole.ADMIN:
        statement = select(LeaveRequest)
        if employee_id is not None:
            statement = statement.where(LeaveRequest.employee_id == employee_id)
        return session.exec(statement.order_by(LeaveRequest.created_at.desc())).all()

    if current_user.employee_id is None:
        return []

    return session.exec(
        select(LeaveRequest)
        .where(LeaveRequest.employee_id == current_user.employee_id)
        .order_by(LeaveRequest.created_at.desc())
    ).all()
