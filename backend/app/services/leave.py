from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from app.models import Employee, LeaveRequest, LeaveStatus, LeaveType, User, UserRole


def calculate_leave_days(leave_request: LeaveRequest) -> int:
    calculated_days = (leave_request.end_date - leave_request.start_date).days + 1
    return max(int(leave_request.total_days or 0), calculated_days)


def get_approved_leave_days(session: Session, employee_id: int, leave_type: LeaveType = LeaveType.ANNUAL) -> int:
    approved_requests = session.exec(select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)).all()
    filtered_requests = [
        request
        for request in approved_requests
        if request.status == LeaveStatus.APPROVED and request.leave_type == leave_type
    ]
    return sum(calculate_leave_days(request) for request in filtered_requests)


def get_leave_type_totals(session: Session, employee_id: int, year: int | None = None) -> dict[LeaveType, int]:
    target_year = year or datetime.utcnow().year
    approved_requests = session.exec(select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)).all()
    totals = {
        LeaveType.ANNUAL: 0,
        LeaveType.SICK: 0,
        LeaveType.CASUAL: 0,
        LeaveType.UNPAID: 0,
    }
    for request in approved_requests:
        if request.status != LeaveStatus.APPROVED:
            continue
        if request.start_date.year != target_year and request.end_date.year != target_year:
            continue
        totals[request.leave_type] = totals.get(request.leave_type, 0) + calculate_leave_days(request)
    return totals


def get_leave_quota_summary(session: Session, employee: Employee, year: int | None = None) -> dict[str, int | str]:
    target_year = year or datetime.utcnow().year
    used_totals = get_leave_type_totals(session, employee.id, target_year)
    annual_total = 20
    sick_total = 10
    casual_total = 5
    annual_used = int(used_totals.get(LeaveType.ANNUAL, 0))
    sick_used = int(used_totals.get(LeaveType.SICK, 0))
    casual_used = int(used_totals.get(LeaveType.CASUAL, 0))
    unpaid_used = int(used_totals.get(LeaveType.UNPAID, 0))
    return {
        "employee_id": int(employee.id),
        "employee_name": employee.name,
        "year": target_year,
        "annual_total": annual_total,
        "annual_used": annual_used,
        "annual_remaining": max(annual_total - annual_used, 0),
        "sick_total": sick_total,
        "sick_used": sick_used,
        "sick_remaining": max(sick_total - sick_used, 0),
        "casual_total": casual_total,
        "casual_used": casual_used,
        "casual_remaining": max(casual_total - casual_used, 0),
        "unpaid_used": unpaid_used,
    }


def get_leave_balance_summary(session: Session, employee: Employee) -> dict[str, float | int | str]:
    used = float(get_approved_leave_days(session, employee.id, LeaveType.ANNUAL))
    total = 20.0
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
