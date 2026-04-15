from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import (
    Candidate,
    Employee,
    EmployeeRole,
    EmploymentType,
    Job,
    JobStatus,
    LeaveQuota,
    LeaveRequest,
    LeaveStatus,
    Notification,
    User,
    UserRole,
)
from backend.app.schemas import (
    AdminCandidateRead,
    AdminEmployeeCreateRequest,
    AdminEmployeeCreateResponse,
    AdminEmployeeRead,
    AdminEmployeeUpdateRequest,
    AdminJobCreateRequest,
    AdminJobUpdateRequest,
    AdminLeaveRead,
    AdminUserRead,
    InterviewEmailDraftResponse,
    InterviewEmailGenerateRequest,
    InterviewEmailSendRequest,
    JobRead,
    LeaveQuotaRead,
    LeaveRequestRead,
    LeaveRequestStatusUpdate,
    PromoteCandidateRequest,
)
from backend.app.services.admin_dashboard import generate_job_post, recommendation_label_for_score, split_full_name
from backend.app.services.ai_email import (
    generate_interview_invitation_email,
    generate_leave_approval_email,
    generate_leave_rejection_email,
    generate_welcome_email,
)
from backend.app.services.email_service import EmailService
from backend.app.services.leave import calculate_leave_days, get_leave_quota_summary
from backend.app.services.recruitment import hydrate_legacy_candidate

router = APIRouter(prefix="/admin", tags=["admin"])


def _clean_text_list(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value and value.strip()]


def _to_job_read(job: Job) -> JobRead:
    return JobRead.model_validate(job)


def _notification_sent_at_for_leave(session: Session, leave_request: LeaveRequest, employee: Employee) -> datetime | None:
    notifications = session.exec(
        select(Notification)
        .where(Notification.employee_id == leave_request.employee_id)
        .where(Notification.notification_type.in_(["leave_approved", "leave_rejected"]))
        .where(Notification.status == "sent")
        .order_by(Notification.sent_at.desc())
    ).all()
    if not notifications:
        return None

    start_token = leave_request.start_date.isoformat()
    end_token = leave_request.end_date.isoformat()
    for notification in notifications:
        blob = f"{notification.subject}\n{notification.body}"
        if start_token in blob and end_token in blob:
            return notification.sent_at
    return notifications[0].sent_at


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


def _to_admin_leave_read(
    leave_request: LeaveRequest,
    employee: Employee,
    *,
    email_sent_at: datetime | None,
) -> AdminLeaveRead:
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
        email_sent_at=email_sent_at,
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
        interview_email_sent=bool(candidate.interview_email_sent),
        interview_date=candidate.interview_date,
        interview_email_sent_at=candidate.interview_email_sent_at,
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


def _normalize_employee_email(email: str) -> str:
    return email.strip().lower()


def _find_employee_by_official_email(session: Session, email: str) -> Employee | None:
    normalized_email = _normalize_employee_email(email)
    employees = session.exec(select(Employee)).all()
    for employee in employees:
        if _normalize_employee_email(employee.official_email) == normalized_email:
            return employee
    return None


def _ensure_leave_quota_exists(session: Session, employee_id: int, year: int) -> None:
    quota = session.exec(
        select(LeaveQuota).where(LeaveQuota.employee_id == employee_id, LeaveQuota.year == year)
    ).first()
    if quota is not None:
        return

    session.add(
        LeaveQuota(
            employee_id=employee_id,
            year=year,
            annual_total=20,
            annual_used=0,
            sick_total=10,
            sick_used=0,
            casual_total=5,
            casual_used=0,
            unpaid_used=0,
        )
    )
    session.commit()


def _sync_user_with_employee(session: Session, employee: Employee) -> User:
    normalized_email = _normalize_employee_email(employee.official_email)
    target_role = UserRole.ADMIN if employee.role == EmployeeRole.ADMIN else UserRole.EMPLOYEE
    user = session.exec(select(User).where(User.email == normalized_email)).first()

    if user is None:
        user = User(
            email=normalized_email,
            full_name=employee.full_name or employee.name,
            hashed_password=employee.password_hash or "",
            role=target_role,
            employee_id=employee.id,
        )
    else:
        if user.employee_id is not None and user.employee_id != employee.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already linked to a different employee account.",
            )
        user.full_name = employee.full_name or employee.name
        user.role = target_role
        user.employee_id = employee.id
        if employee.password_hash:
            user.hashed_password = employee.password_hash

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _to_admin_employee_read(session: Session, employee: Employee) -> AdminEmployeeRead:
    summary = get_leave_quota_summary(session, employee)
    return AdminEmployeeRead(
        employee_id=int(employee.id),
        full_name=employee.full_name or employee.name,
        official_email=employee.official_email,
        department=employee.department,
        designation=employee.designation,
        date_of_joining=employee.date_of_joining,
        role=employee.role,
        is_active=employee.is_active,
        password_set=bool(employee.password_hash),
        annual_total=int(summary["annual_total"]),
        annual_used=int(summary["annual_used"]),
        annual_remaining=int(summary["annual_remaining"]),
        sick_total=int(summary["sick_total"]),
        sick_used=int(summary["sick_used"]),
        sick_remaining=int(summary["sick_remaining"]),
        casual_total=int(summary["casual_total"]),
        casual_used=int(summary["casual_used"]),
        casual_remaining=int(summary["casual_remaining"]),
        unpaid_used=int(summary["unpaid_used"]),
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

    jobs_by_id = {job.job_id: job for job in session.exec(select(Job)).all() if job.job_id is not None}
    return _to_admin_candidate_read(candidate, jobs_by_id)


@router.post("/candidates/{candidate_id}/generate-interview-email", response_model=InterviewEmailDraftResponse)
def generate_candidate_interview_email(
    candidate_id: int,
    payload: InterviewEmailGenerateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> InterviewEmailDraftResponse:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    interview_date = payload.interview_date
    if interview_date <= datetime.now(timezone.utc).date():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Interview date must be in the future.")

    job = session.get(Job, candidate.job_id) if candidate.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title
    generated = generate_interview_invitation_email(
        candidate_name=f"{candidate.first_name} {candidate.last_name}".strip() or candidate.name,
        job_title=job_title,
        interview_date=interview_date,
        interview_time=payload.interview_time,
        interview_format=payload.interview_format,
        location_or_link=payload.location_or_link,
        additional_notes=payload.additional_notes,
    )

    return InterviewEmailDraftResponse(
        to_email=candidate.email,
        subject=generated["subject"],
        body=generated["body"],
    )


@router.post("/candidates/{candidate_id}/send-interview-email")
def send_candidate_interview_email(
    candidate_id: int,
    payload: InterviewEmailSendRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    if candidate.interview_email_sent:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview email has already been sent.")

    subject = payload.subject.strip()
    body = payload.body.strip()
    if not subject or not body:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Both subject and body are required.")

    sent = EmailService.send_email(
        payload.to_email.strip(),
        subject,
        body,
        session=session,
        employee_id=None,
        notification_type="interview_invite",
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Interview email could not be sent. Please verify email provider configuration.",
        )

    candidate.interview_email_sent = True
    candidate.interview_date = payload.interview_date or candidate.interview_date
    candidate.interview_email_sent_at = datetime.utcnow()
    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    return {"message": "Interview invitation sent successfully."}


@router.get("/leaves", response_model=list[AdminLeaveRead])
def list_admin_leaves(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminLeaveRead]:
    leave_requests = session.exec(select(LeaveRequest).order_by(LeaveRequest.submitted_at.desc())).all()
    employees = {employee.id: employee for employee in session.exec(select(Employee)).all()}
    results: list[AdminLeaveRead] = []
    for leave_request in leave_requests:
        employee = employees.get(leave_request.employee_id)
        if employee is None:
            continue
        results.append(
            _to_admin_leave_read(
                leave_request,
                employee,
                email_sent_at=_notification_sent_at_for_leave(session, leave_request, employee),
            )
        )
    return results


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

    rejection_note = payload.hr_note.strip()
    if payload.status == LeaveStatus.REJECTED and not rejection_note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A reason (hr_note) is required when rejecting a leave.",
        )

    leave_request.status = payload.status
    leave_request.hr_note = rejection_note
    leave_request.total_days = calculate_leave_days(leave_request)
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)

    employee = session.get(Employee, leave_request.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    if leave_request.status == LeaveStatus.APPROVED:
        email_payload = generate_leave_approval_email(
            full_name=employee.full_name or employee.name,
            department=employee.department,
            leave_type=leave_request.leave_type.value,
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
            total_days=leave_request.total_days,
            reason=leave_request.reason,
        )
        notification_type = "leave_approved"
    else:
        email_payload = generate_leave_rejection_email(
            full_name=employee.full_name or employee.name,
            department=employee.department,
            leave_type=leave_request.leave_type.value,
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
            total_days=leave_request.total_days,
            hr_note=rejection_note,
        )
        notification_type = "leave_rejected"

    EmailService.send_email(
        employee.official_email,
        email_payload["subject"],
        email_payload["body"],
        session=session,
        employee_id=employee.id,
        notification_type=notification_type,
    )

    sent_notification = session.exec(
        select(Notification)
        .where(Notification.employee_id == employee.id)
        .where(Notification.notification_type == notification_type)
        .where(Notification.status == "sent")
        .order_by(Notification.sent_at.desc())
    ).first()

    return _to_admin_leave_read(
        leave_request,
        employee,
        email_sent_at=sent_notification.sent_at if sent_notification is not None else None,
    )


@router.get("/employees/leave-quota", response_model=list[LeaveQuotaRead])
def list_leave_quotas(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[LeaveQuotaRead]:
    employees = session.exec(select(Employee).order_by(Employee.name.asc())).all()
    return [LeaveQuotaRead(**get_leave_quota_summary(session, employee)) for employee in employees]


@router.get("/employees", response_model=list[AdminEmployeeRead])
def list_admin_employees(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminEmployeeRead]:
    employees = session.exec(select(Employee).order_by(Employee.date_of_joining.desc(), Employee.name.asc())).all()
    return [_to_admin_employee_read(session, employee) for employee in employees]


@router.get("/employees/{employee_id}", response_model=AdminEmployeeRead)
def get_admin_employee(
    employee_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminEmployeeRead:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    return _to_admin_employee_read(session, employee)


@router.post("/employees", response_model=AdminEmployeeCreateResponse, status_code=status.HTTP_201_CREATED)
def create_admin_employee(
    payload: AdminEmployeeCreateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminEmployeeCreateResponse:
    normalized_email = _normalize_employee_email(payload.official_email)
    existing = _find_employee_by_official_email(session, normalized_email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee with this email already exists.")

    employee = Employee(
        name=payload.full_name.strip(),
        full_name=payload.full_name.strip(),
        official_email=normalized_email,
        department=payload.department.strip(),
        designation=payload.designation.strip(),
        date_of_joining=payload.date_of_joining,
        password_hash=None,
        is_active=True,
        role=payload.role,
        annual_allowance=20,
        leave_balance=20,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)

    current_year = datetime.utcnow().year
    _ensure_leave_quota_exists(session, int(employee.id), current_year)
    _sync_user_with_employee(session, employee)

    welcome_email = generate_welcome_email(
        full_name=employee.full_name or employee.name,
        designation=employee.designation,
        department=employee.department,
        start_date=employee.date_of_joining,
    )
    EmailService.send_email(
        employee.official_email,
        welcome_email["subject"],
        welcome_email["body"],
        session=session,
        employee_id=employee.id,
        notification_type="welcome",
    )

    return AdminEmployeeCreateResponse(
        message="Employee created successfully.",
        employee_id=int(employee.id),
    )


@router.patch("/employees/{employee_id}", response_model=AdminEmployeeRead)
def update_admin_employee(
    employee_id: int,
    payload: AdminEmployeeUpdateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminEmployeeRead:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    updates = payload.model_dump(exclude_unset=True)
    for field_name, field_value in updates.items():
        setattr(employee, field_name, field_value)

    session.add(employee)
    session.commit()
    session.refresh(employee)
    _sync_user_with_employee(session, employee)
    return _to_admin_employee_read(session, employee)


@router.delete("/employees/{employee_id}")
def soft_delete_admin_employee(
    employee_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    employee.is_active = False
    session.add(employee)
    session.commit()
    session.refresh(employee)

    user = session.exec(select(User).where(User.employee_id == employee.id)).first()
    if user is not None:
        user.employee_id = employee.id
        session.add(user)
        session.commit()

    return {"message": "Employee deactivated successfully."}


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
        role=EmployeeRole.EMPLOYEE,
        annual_allowance=payload.annual_allowance,
        leave_balance=payload.annual_allowance,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)

    _ensure_leave_quota_exists(session, int(employee.id), datetime.utcnow().year)

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
