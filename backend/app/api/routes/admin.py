from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi import Response, status
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import Candidate, Employee, EmploymentType, Job, JobStatus, LeaveRequest, LeaveStatus, User, UserRole
from backend.app.schemas import (
    AdminCandidateRead,
    AdminJobCreateRequest,
    AdminJobUpdateRequest,
    AdminLeaveRead,
    AdminUserRead,
    JobRead,
    LeaveQuotaRead,
    LeaveRequestRead,
    LeaveRequestStatusUpdate,
    PromoteCandidateRequest,
)
from backend.app.services.admin_dashboard import generate_job_post, recommendation_label_for_score, split_full_name
from backend.app.services.leave import calculate_leave_days, get_leave_quota_summary
from backend.app.services.recruitment import hydrate_legacy_candidate

router = APIRouter(prefix="/admin", tags=["admin"])


def _clean_text_list(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value and value.strip()]


def _to_job_read(job: Job) -> JobRead:
    return JobRead.model_validate(job)


def _to_leave_read(leave_request: LeaveRequest, employee: Employee) -> LeaveRequestRead:
    return LeaveRequestRead(
        id=leave_request.id,
        employee_id=leave_request.employee_id,
        employee_name=employee.name,
        department=employee.department,
        leave_type=leave_request.leave_type,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        total_days=calculate_leave_days(leave_request),
        reason=leave_request.reason,
        status=leave_request.status,
        hr_note=leave_request.hr_note,
        handover_contact=leave_request.handover_contact,
        handover_notes=leave_request.handover_notes,
        urgency_level=leave_request.urgency_level,
        privacy_flagged=leave_request.privacy_flagged,
        submitted_at=leave_request.submitted_at,
        created_at=leave_request.created_at,
    )


def _to_admin_leave_read(leave_request: LeaveRequest, employee: Employee) -> AdminLeaveRead:
    return AdminLeaveRead(
        leave_id=leave_request.id,
        employee_id=leave_request.employee_id,
        employee_name=employee.name,
        leave_type=leave_request.leave_type,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        total_days=calculate_leave_days(leave_request),
        reason=leave_request.reason,
        status=leave_request.status,
        hr_note=leave_request.hr_note,
        submitted_at=leave_request.submitted_at,
    )


def _normalize_transcript(candidate: Candidate) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    score_breakdown: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []

    for index, answer in enumerate(candidate.raw_answers):
        if not isinstance(answer, dict):
            continue
        fallback_question = candidate.screening_questions[index] if index < len(candidate.screening_questions) else ""
        question = str(answer.get("question") or fallback_question)
        answer_text = str(answer.get("answer", "")).strip()
        score = int(answer.get("score", 0) or 0)
        justification = str(answer.get("justification", "")).strip()
        source = str(answer.get("source", "system")).strip()
        item = {
            "question": question,
            "answer": answer_text,
            "score": score,
            "justification": justification,
            "source": source,
        }
        score_breakdown.append(item)
        transcript.append(item)

    if not transcript:
        for index, question in enumerate(candidate.screening_questions):
            transcript.append(
                {
                    "question": question,
                    "answer": "",
                    "score": 0,
                    "justification": "",
                    "source": "pending" if index >= candidate.current_question_index else "system",
                }
            )

    return transcript, score_breakdown


def _to_admin_candidate_read(candidate: Candidate, jobs_by_id: dict[int, Job]) -> AdminCandidateRead:
    first_name = candidate.first_name.strip()
    last_name = candidate.last_name.strip()
    if not first_name:
        first_name, last_name = split_full_name(candidate.name)

    interview_transcript, score_breakdown = _normalize_transcript(candidate)
    job_title = jobs_by_id[candidate.job_id].title if candidate.job_id in jobs_by_id else candidate.role_title
    screening_score = int(candidate.ai_score)
    return AdminCandidateRead(
        candidate_id=int(candidate.id),
        first_name=first_name,
        last_name=last_name,
        email=candidate.email,
        job_id=candidate.job_id,
        job_position=job_title,
        cv_summary=(candidate.cv_summary or candidate.summary or "").strip(),
        screening_score=screening_score,
        recommendation_label=recommendation_label_for_score(screening_score),
        interview_transcript=interview_transcript,
        score_breakdown=score_breakdown,
        applied_at=candidate.created_at,
    )


def _ensure_leave_status_updatable(status_value: LeaveStatus) -> None:
    if status_value not in {LeaveStatus.APPROVED, LeaveStatus.REJECTED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Leave status can only be updated to approved or rejected from the admin dashboard.",
        )


@router.get("/jobs", response_model=list[JobRead])
def list_jobs(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[JobRead]:
    jobs = session.exec(select(Job).order_by(Job.created_at.desc())).all()
    return [_to_job_read(job) for job in jobs]


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: AdminJobCreateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> JobRead:
    generated = generate_job_post(payload.title.strip())
    job = Job(
        title=payload.title.strip(),
        description=str(generated["description"]).strip(),
        required_skills=_clean_text_list(generated.get("required_skills")),
        experience_years=int(generated.get("experience_years", 0)),
        employment_type=EmploymentType(str(generated.get("employment_type", EmploymentType.FULL_TIME.value))),
        salary_range=str(generated.get("salary_range", "")).strip() or None,
        responsibilities=_clean_text_list(generated.get("responsibilities")),
        nice_to_have_qualifications=_clean_text_list(generated.get("nice_to_have_qualifications")),
        status=JobStatus.OPEN,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return _to_job_read(job)


@router.patch("/jobs/{job_id}", response_model=JobRead)
def update_job(
    job_id: int,
    payload: AdminJobUpdateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> JobRead:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    updates = payload.model_dump(exclude_unset=True)
    for field_name, field_value in updates.items():
        if field_name in {"required_skills", "responsibilities", "nice_to_have_qualifications"}:
            setattr(job, field_name, _clean_text_list(field_value))
        else:
            setattr(job, field_name, field_value)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return _to_job_read(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_job(
    job_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> Response:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    candidates = session.exec(select(Candidate).where(Candidate.job_id == job_id)).all()
    for candidate in candidates:
        candidate.job_id = None
        session.add(candidate)

    session.delete(job)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/candidates", response_model=list[AdminCandidateRead])
def list_admin_candidates(
    job_id: int | None = Query(default=None),
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminCandidateRead]:
    candidates = session.exec(select(Candidate).order_by(Candidate.ai_score.desc(), Candidate.created_at.desc())).all()
    jobs = session.exec(select(Job)).all()
    jobs_by_id = {job.job_id: job for job in jobs if job.job_id is not None}

    changed = False
    hydrated_candidates: list[Candidate] = []
    for candidate in candidates:
        candidate_changed = hydrate_legacy_candidate(candidate)
        hydrated_candidates.append(candidate)
        if candidate_changed:
            session.add(candidate)
            changed = True

    if changed:
        session.commit()
        for candidate in hydrated_candidates:
            session.refresh(candidate)

    filtered_candidates = []
    for candidate in hydrated_candidates:
        if job_id is not None:
            matches_selected_job = candidate.job_id == job_id
            if not matches_selected_job and job_id in jobs_by_id:
                matches_selected_job = candidate.role_title.strip().lower() == jobs_by_id[job_id].title.strip().lower()
            if not matches_selected_job:
                continue
        filtered_candidates.append(candidate)

    return [_to_admin_candidate_read(candidate, jobs_by_id) for candidate in filtered_candidates]


@router.get("/candidates/{candidate_id}", response_model=AdminCandidateRead)
def get_admin_candidate(
    candidate_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminCandidateRead:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    if hydrate_legacy_candidate(candidate):
        session.add(candidate)
        session.commit()
        session.refresh(candidate)

    jobs_by_id = {
        job.job_id: job
        for job in session.exec(select(Job)).all()
        if job.job_id is not None
    }
    return _to_admin_candidate_read(candidate, jobs_by_id)


@router.get("/leaves", response_model=list[AdminLeaveRead])
def list_admin_leaves(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminLeaveRead]:
    leave_requests = session.exec(select(LeaveRequest).order_by(LeaveRequest.submitted_at.desc())).all()
    employees = {employee.id: employee for employee in session.exec(select(Employee)).all()}
    return [
        _to_admin_leave_read(leave_request, employees[leave_request.employee_id])
        for leave_request in leave_requests
        if leave_request.employee_id in employees
    ]


@router.patch("/leaves/{leave_id}", response_model=AdminLeaveRead)
def update_admin_leave(
    leave_id: int,
    payload: LeaveRequestStatusUpdate,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminLeaveRead:
    _ensure_leave_status_updatable(payload.status)
    leave_request = session.get(LeaveRequest, leave_id)
    if leave_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave request not found.")

    leave_request.status = payload.status
    leave_request.hr_note = payload.hr_note.strip()
    leave_request.total_days = calculate_leave_days(leave_request)
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)

    employee = session.get(Employee, leave_request.employee_id)
    return _to_admin_leave_read(leave_request, employee)


@router.get("/employees/leave-quota", response_model=list[LeaveQuotaRead])
def list_leave_quotas(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[LeaveQuotaRead]:
    employees = session.exec(select(Employee).order_by(Employee.name.asc())).all()
    return [LeaveQuotaRead(**get_leave_quota_summary(session, employee)) for employee in employees]


@router.get("/all-leaves", response_model=list[LeaveRequestRead])
def list_all_leaves_legacy(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[LeaveRequestRead]:
    leave_requests = session.exec(select(LeaveRequest).order_by(LeaveRequest.submitted_at.desc())).all()
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.role != UserRole.CANDIDATE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only candidate users can be promoted.")

    employee = Employee(
        name=user.full_name,
        full_name=user.full_name,
        official_email=user.email.strip().lower(),
        department=payload.department,
        designation="Employee",
        date_of_joining=datetime.now(timezone.utc).date(),
        is_active=True,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leave request not found.")

    leave_request.status = LeaveStatus.APPROVED
    leave_request.total_days = calculate_leave_days(leave_request)
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    employee = session.get(Employee, leave_request.employee_id)
    return _to_leave_read(leave_request, employee)
