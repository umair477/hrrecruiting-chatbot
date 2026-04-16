from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.database import get_session
from app.deps import get_current_user, require_roles
from app.models import (
    AuditEvent,
    Candidate,
    CandidatePortalToken,
    CandidateStatus,
    Employee,
    EmployeeRole,
    LeaveRequest,
    LeaveStatus,
    User,
    UserRole,
)
from app.schemas import (
    AuditEventRead,
    CandidatePortalStatusResponse,
    CandidateStatusLinkRequest,
    CandidateStatusLinkResponse,
    CandidateTalentPoolItem,
    CandidateTalentPoolResponse,
    InterviewSlotRead,
    InterviewSlotResponse,
    ManagerLeaveReviewRequest,
    PolicyAssistantRequest,
    PolicyAssistantResponse,
)
from app.services.audit import log_audit_event


router = APIRouter(prefix="/innovation", tags=["innovation"])

_POLICY_SNIPPETS = {
    "carry forward": "Annual leave carry forward is capped and subject to HR policy cut-off dates.",
    "probation": "Employees on probation can apply for sick leave and unpaid leave; annual leave usage may be restricted.",
    "sick": "Sick leave requests should include clear dates and a reason. Extended periods may require documentation.",
    "interview": "Interview scheduling follows shortlist review and must include candidate confirmation.",
}


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@router.post("/candidates/status-link", response_model=CandidateStatusLinkResponse)
def create_candidate_status_link(
    payload: CandidateStatusLinkRequest,
    session: Session = Depends(get_session),
) -> CandidateStatusLinkResponse:
    candidate = session.exec(
        select(Candidate).where(Candidate.email == payload.email.strip().lower())
    ).first()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    token = CandidatePortalToken(
        candidate_id=int(candidate.id),
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    log_audit_event(
        session=session,
        actor_type="candidate",
        actor_id=str(candidate.id),
        event_type="candidate.status_link_created",
        entity_type="candidate_portal_token",
        entity_id=token.token,
        details={"candidate_id": int(candidate.id), "expires_at": token.expires_at.isoformat()},
    )
    return CandidateStatusLinkResponse(access_token=token.token, expires_at=token.expires_at)


@router.get("/candidates/portal/{access_token}", response_model=CandidatePortalStatusResponse)
def get_candidate_portal_status(
    access_token: str,
    session: Session = Depends(get_session),
) -> CandidatePortalStatusResponse:
    portal_token = session.exec(select(CandidatePortalToken).where(CandidatePortalToken.token == access_token)).first()
    if portal_token is None or _as_utc_naive(portal_token.expires_at) < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.")

    candidate = session.get(Candidate, portal_token.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    return CandidatePortalStatusResponse(
        candidate_id=int(candidate.id),
        full_name=(candidate.name or f"{candidate.first_name} {candidate.last_name}").strip(),
        email=candidate.email,
        job_title=candidate.role_title,
        status=candidate.status,
        interview_status=candidate.interview_status,
        interview_date=candidate.interview_date,
        recommendation_label=candidate.recommendation_label,
        updated_at=candidate.created_at,
    )


@router.get("/talent-pool/search", response_model=CandidateTalentPoolResponse)
def search_talent_pool(
    skill: str | None = None,
    min_score: int = 0,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> CandidateTalentPoolResponse:
    candidates = session.exec(select(Candidate)).all()
    skill_filter = skill.strip().lower() if skill else ""
    items: list[CandidateTalentPoolItem] = []
    for candidate in candidates:
        if candidate.status == CandidateStatus.REJECTED:
            continue
        total_score = int(candidate.ai_score or 0)
        if total_score < min_score:
            continue
        normalized_skills = [str(item).strip() for item in (candidate.skills or []) if str(item).strip()]
        if skill_filter and not any(skill_filter in entry.lower() for entry in normalized_skills):
            continue
        items.append(
            CandidateTalentPoolItem(
                candidate_id=int(candidate.id),
                full_name=(candidate.name or f"{candidate.first_name} {candidate.last_name}").strip(),
                email=candidate.email,
                skills=normalized_skills,
                recommendation_label=candidate.recommendation_label,
                score=total_score,
                status=candidate.status,
            )
        )
    items.sort(key=lambda row: row.score, reverse=True)
    return CandidateTalentPoolResponse(items=items)


@router.get("/candidates/{candidate_id}/interview-slots", response_model=InterviewSlotResponse)
def get_interview_slots(candidate_id: int, session: Session = Depends(get_session)) -> InterviewSlotResponse:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=1, hours=14)
    slots = [
        InterviewSlotRead(start_at=base + timedelta(days=offset), end_at=base + timedelta(days=offset, hours=1), timezone="UTC")
        for offset in range(0, 3)
    ]
    return InterviewSlotResponse(candidate_id=candidate_id, job_title=candidate.role_title, slots=slots)


@router.post("/policy/ask", response_model=PolicyAssistantResponse)
def ask_policy_question(payload: PolicyAssistantRequest) -> PolicyAssistantResponse:
    question = payload.question.strip().lower()
    matched_sources: list[str] = []
    answers: list[str] = []
    for key, snippet in _POLICY_SNIPPETS.items():
        if key in question:
            matched_sources.append(f"policy::{key}")
            answers.append(snippet)

    if not answers:
        answers = [
            "I could not find an exact policy match. Please contact HR for an authoritative answer.",
        ]
        matched_sources = ["policy::fallback"]
    return PolicyAssistantResponse(answer=" ".join(answers), sources=matched_sources)


@router.patch("/manager/leaves/{leave_id}")
def review_leave_as_manager(
    leave_id: int,
    payload: ManagerLeaveReviewRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    employee = session.get(Employee, current_user.employee_id) if current_user.employee_id else None
    if employee is None or employee.role not in {EmployeeRole.ADMIN, EmployeeRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Manager-level role required.")

    leave_request = session.get(LeaveRequest, leave_id)
    if leave_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave request not found.")

    leave_request.status = LeaveStatus.APPROVED if payload.status == "approved" else LeaveStatus.REJECTED
    leave_request.hr_note = payload.note.strip()
    session.add(leave_request)
    session.commit()
    log_audit_event(
        session=session,
        actor_type="employee",
        actor_id=str(employee.id),
        event_type="leave.manager_reviewed",
        entity_type="leave_request",
        entity_id=str(leave_id),
        details={"status": payload.status, "note": payload.note.strip()},
    )
    return {"message": "Leave review recorded."}


@router.get("/audit/events", response_model=list[AuditEventRead])
def list_audit_events(
    limit: int = 50,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AuditEventRead]:
    safe_limit = min(max(limit, 1), 200)
    events = session.exec(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(safe_limit)).all()
    return [AuditEventRead.model_validate(event) for event in events]


@router.get("/routing/intent")
def intent_router_preview(message: str) -> dict[str, str | float]:
    from hr_chatbot.router import classify_workflow

    decision = classify_workflow(message)
    fingerprint = sha256(message.strip().lower().encode("utf-8")).hexdigest()[:16]
    return {
        "workflow": decision.workflow.value,
        "confidence": decision.confidence,
        "rationale": decision.rationale,
        "fingerprint": fingerprint,
    }
