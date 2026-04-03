from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import Candidate, Employee, LeaveRequest, LeaveStatus, User, UserRole
from backend.app.schemas import AnalyticsOverview, AnalyticsPoint, MetricCard

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AnalyticsOverview:
    candidates = session.exec(select(Candidate)).all()
    employees = session.exec(select(Employee)).all()
    leave_requests = session.exec(select(LeaveRequest)).all()

    pending_leaves = sum(1 for leave_request in leave_requests if leave_request.status == LeaveStatus.PENDING)
    shortlisted = sum(1 for candidate in candidates if candidate.ai_score >= 85)
    avg_score = int(round(sum(candidate.ai_score for candidate in candidates) / max(len(candidates), 1)))

    department_counter = Counter(employee.department for employee in employees)
    monthly_hires = [
        AnalyticsPoint(label="Jan", value=4),
        AnalyticsPoint(label="Feb", value=7),
        AnalyticsPoint(label="Mar", value=5),
        AnalyticsPoint(label="Apr", value=8),
        AnalyticsPoint(label="May", value=6),
        AnalyticsPoint(label="Jun", value=9),
    ]

    return AnalyticsOverview(
        stats=[
            MetricCard(label="Total Candidates", value=str(len(candidates)), change="+3 this sprint"),
            MetricCard(label="Shortlisted", value=str(shortlisted), change="+2 reviewed"),
            MetricCard(label="Pending Leaves", value=str(pending_leaves), change="Awaiting HR action"),
            MetricCard(label="Avg Match Score", value=f"{avg_score}%", change="Based on AI scorecards"),
        ],
        monthly_hires=monthly_hires,
        candidates_by_department=[
            AnalyticsPoint(label=department, value=value)
            for department, value in department_counter.items()
        ],
    )

