from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Iterable
from urllib.parse import quote_plus
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, select

from backend.app.core.config import settings
from backend.app.core.database import get_session
from backend.app.deps import get_current_user
from backend.app.models import (
    Candidate,
    CandidateStatus,
    Employee,
    EmployeeRole,
    Interview,
    InterviewScheduleStatus,
    Job,
    User,
    UserRole,
)
from backend.app.schemas import (
    InterviewAvailableSlotRead,
    InterviewAvailableSlotsResponse,
    InterviewBookingConfirmRequest,
    InterviewBookingConfirmResponse,
    InterviewBookingPortalRead,
    InterviewBookingRead,
    InterviewBookingRequestCreate,
    InterviewBookingRequestCreateResponse,
    InterviewCancelRequest,
    InterviewProposedSlot,
    InterviewRescheduleRequest,
)
from backend.app.services.ai_email import (
    generate_interview_booking_confirmation_email,
    generate_interview_cancellation_email,
    generate_interview_self_scheduling_email,
)
from backend.app.services.calendar_factory import CalendarServiceFactory
from backend.app.services.email_service import EmailService

router = APIRouter(tags=["interviews"])


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _candidate_name(candidate: Candidate) -> str:
    first = candidate.first_name.strip()
    last = candidate.last_name.strip()
    full = f"{first} {last}".strip()
    return full or candidate.name


def _booking_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/schedule/{token}"


def _validate_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="date_to must be on or after date_from.")
    if (date_to - date_from).days > 14:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Date range cannot exceed 2 weeks.")


def _format_slot_display(start_at: datetime, end_at: datetime) -> str:
    return f"{start_at.strftime('%A, %b %d')} · {start_at.strftime('%I:%M %p')} - {end_at.strftime('%I:%M %p')}"


def _to_slot_read(start_at: datetime, end_at: datetime, *, slot_id: str | None = None) -> InterviewAvailableSlotRead:
    return InterviewAvailableSlotRead(
        slot_id=slot_id or str(uuid4()),
        start=start_at,
        end=end_at,
        formatted_display=_format_slot_display(start_at, end_at),
        day_of_week=start_at.strftime("%A"),
    )


def _serialize_slots(slots: Iterable[InterviewProposedSlot]) -> list[dict[str, str]]:
    normalized: list[tuple[datetime, datetime]] = []
    seen: set[tuple[str, str]] = set()
    now_utc = datetime.now(timezone.utc)
    for slot in slots:
        start_at = _as_utc(slot.start)
        end_at = _as_utc(slot.end)
        if end_at <= start_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Each proposed slot must end after it starts.")
        if start_at <= now_utc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Proposed slots must be in the future.")
        dedupe_key = (start_at.isoformat(), end_at.isoformat())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append((start_at, end_at))

    if len(normalized) < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one valid slot is required.")

    normalized.sort(key=lambda pair: pair[0])
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in normalized]


def _deserialize_slots(raw_slots: object) -> list[InterviewProposedSlot]:
    payload = raw_slots
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = []

    if not isinstance(payload, list):
        return []

    slots: list[InterviewProposedSlot] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        start_raw = item.get("start")
        end_raw = item.get("end")
        if not start_raw or not end_raw:
            continue
        try:
            start_at = _as_utc(datetime.fromisoformat(str(start_raw).replace("Z", "+00:00")))
            end_at = _as_utc(datetime.fromisoformat(str(end_raw).replace("Z", "+00:00")))
        except ValueError:
            continue
        if end_at <= start_at:
            continue
        slots.append(InterviewProposedSlot(start=start_at, end=end_at))

    slots.sort(key=lambda slot: slot.start)
    return slots


def _refresh_expired_status(interview: Interview) -> bool:
    if interview.status not in {InterviewScheduleStatus.PENDING_BOOKING, InterviewScheduleStatus.RESCHEDULED}:
        return False
    token_expires_at = interview.token_expires_at
    if token_expires_at is None:
        interview.status = InterviewScheduleStatus.EXPIRED
        interview.updated_at = datetime.utcnow()
        return True

    if _as_utc(token_expires_at) >= datetime.now(timezone.utc):
        return False
    interview.status = InterviewScheduleStatus.EXPIRED
    interview.updated_at = datetime.utcnow()
    return True


def _slot_matches(proposed: list[InterviewProposedSlot], selected_start: datetime, selected_end: datetime) -> bool:
    for slot in proposed:
        if abs((slot.start - selected_start).total_seconds()) < 1 and abs((slot.end - selected_end).total_seconds()) < 1:
            return True
    return False


def _collect_emails(candidate: Candidate, interviewer_ids: list[int], session: Session) -> tuple[list[str], list[str]]:
    interviewer_emails: list[str] = []
    if interviewer_ids:
        for employee in session.exec(select(Employee).where(Employee.id.in_(interviewer_ids))).all():
            if employee.official_email.strip():
                interviewer_emails.append(employee.official_email.strip())

    hr_email = settings.email_from_address.strip()
    all_emails = [candidate.email.strip(), *interviewer_emails]
    if hr_email:
        all_emails.append(hr_email)

    deduped: list[str] = []
    seen: set[str] = set()
    for email in all_emails:
        lowered = email.lower()
        if not email or lowered in seen:
            continue
        deduped.append(email)
        seen.add(lowered)

    return deduped, interviewer_emails


def _to_booking_read(interview: Interview, candidate: Candidate, job_title: str) -> InterviewBookingRead:
    slots = _deserialize_slots(interview.proposed_slots)
    return InterviewBookingRead(
        interview_id=int(interview.interview_id),
        candidate_id=int(candidate.id),
        candidate_name=_candidate_name(candidate),
        candidate_email=candidate.email,
        job_id=interview.job_id,
        job_title=job_title,
        format=interview.format,
        location_or_link=interview.location_or_link,
        interviewer_ids=[int(item) for item in (interview.interviewer_ids or [])],
        proposed_slots=slots,
        selected_slot_start=interview.selected_slot_start,
        selected_slot_end=interview.selected_slot_end,
        token_expires_at=interview.token_expires_at,
        status=interview.status,
        meet_link=interview.meet_link,
        notes=interview.notes,
        created_at=interview.created_at,
    )


def _require_admin_or_manager(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> User:
    if current_user.role == UserRole.ADMIN:
        return current_user

    if current_user.role == UserRole.EMPLOYEE and current_user.employee_id is not None:
        employee = session.get(Employee, current_user.employee_id)
        if employee is not None and employee.role in {EmployeeRole.ADMIN, EmployeeRole.MANAGER}:
            return current_user

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")


def _event_location(interview: Interview, meet_url: str | None) -> str:
    if meet_url:
        return meet_url
    return interview.location_or_link.strip()


def _google_calendar_url(title: str, details: str, location: str, start_at: datetime, end_at: datetime) -> str:
    start_token = start_at.strftime("%Y%m%dT%H%M%SZ")
    end_token = end_at.strftime("%Y%m%dT%H%M%SZ")
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote_plus(title)}"
        f"&details={quote_plus(details)}"
        f"&location={quote_plus(location)}"
        f"&dates={start_token}%2F{end_token}"
    )


def _outlook_calendar_url(title: str, details: str, location: str, start_at: datetime, end_at: datetime) -> str:
    return (
        "https://outlook.office.com/calendar/0/deeplink/compose?path=%2Fcalendar%2Faction%2Fcompose"
        f"&subject={quote_plus(title)}"
        f"&body={quote_plus(details)}"
        f"&location={quote_plus(location)}"
        f"&startdt={quote_plus(start_at.isoformat())}"
        f"&enddt={quote_plus(end_at.isoformat())}"
    )


@router.get("/admin/interviews/available-slots", response_model=InterviewAvailableSlotsResponse)
def get_admin_available_slots(
    date_from: date,
    date_to: date,
    duration_minutes: int | None = Query(default=None, ge=15, le=180),
    format: str | None = Query(default=None),
    _: User = Depends(_require_admin_or_manager),
) -> InterviewAvailableSlotsResponse:
    _validate_range(date_from, date_to)

    _ = format  # Interview format can influence downstream UI behavior but does not change freebusy lookup yet.

    effective_duration = duration_minutes or settings.interview_duration_minutes
    range_start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    range_end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)

    calendar_service = CalendarServiceFactory.get_service()
    slots = calendar_service.get_available_slots(
        range_start,
        range_end,
        effective_duration,
        {
            "start": settings.working_hours_start,
            "end": settings.working_hours_end,
        },
    )

    max_slots = min(max(settings.slots_to_propose, 1), 10)
    mapped = [_to_slot_read(slot["start"], slot["end"]) for slot in slots[:max_slots]]
    return InterviewAvailableSlotsResponse(slots=mapped)


@router.post(
    "/admin/interviews/create-booking-request",
    response_model=InterviewBookingRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking_request(
    payload: InterviewBookingRequestCreate,
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> InterviewBookingRequestCreateResponse:
    candidate = session.get(Candidate, payload.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    job_id = payload.job_id if payload.job_id is not None else candidate.job_id
    job = session.get(Job, job_id) if job_id is not None else None

    booking_token = str(uuid4())
    token_expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, settings.booking_token_expiry_hours))
    booking_url = _booking_url(booking_token)

    proposed_slots = _serialize_slots(payload.proposed_slots)
    interview = Interview(
        candidate_id=int(candidate.id),
        job_id=job_id,
        booking_token=booking_token,
        token_expires_at=token_expires_at,
        proposed_slots=proposed_slots,
        format=payload.format.strip(),
        location_or_link=payload.location_or_link.strip(),
        interviewer_ids=sorted({int(item) for item in payload.interviewer_ids if int(item) > 0}),
        notes=payload.notes.strip(),
        status=InterviewScheduleStatus.PENDING_BOOKING,
    )

    session.add(interview)
    session.commit()
    session.refresh(interview)

    job_title = job.title if job is not None else candidate.role_title
    email_payload = generate_interview_self_scheduling_email(
        candidate_name=_candidate_name(candidate),
        job_title=job_title,
        interview_format=interview.format,
        booking_url=booking_url,
        booking_deadline=token_expires_at,
        additional_notes=interview.notes,
    )

    email_sent = EmailService.send_email(
        candidate.email,
        email_payload["subject"],
        email_payload["body"],
        session=session,
        employee_id=None,
        notification_type="interview_booking_invite",
    )

    if email_sent:
        candidate.interview_email_sent = True
        candidate.interview_email_sent_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    return InterviewBookingRequestCreateResponse(
        interview_id=int(interview.interview_id),
        booking_token=booking_token,
        booking_url=booking_url,
        token_expires_at=token_expires_at,
        email_subject=email_payload["subject"],
        email_body=email_payload["body"],
        email_sent=email_sent,
    )


@router.get("/admin/interviews", response_model=list[InterviewBookingRead])
def list_admin_interviews(
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> list[InterviewBookingRead]:
    interviews = session.exec(select(Interview).order_by(Interview.created_at.desc())).all()
    candidates = {
        candidate.id: candidate
        for candidate in session.exec(select(Candidate)).all()
        if candidate.id is not None
    }
    jobs = {job.job_id: job for job in session.exec(select(Job)).all() if job.job_id is not None}

    changed = False
    result: list[InterviewBookingRead] = []
    for interview in interviews:
        changed = _refresh_expired_status(interview) or changed

        candidate = candidates.get(interview.candidate_id)
        if candidate is None:
            continue
        job_title = jobs[interview.job_id].title if interview.job_id in jobs else candidate.role_title
        result.append(_to_booking_read(interview, candidate, job_title))

    if changed:
        session.commit()

    return result


@router.post("/admin/interviews/{interview_id}/cancel")
def cancel_interview(
    interview_id: int,
    payload: InterviewCancelRequest,
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")

    if interview.status in {InterviewScheduleStatus.CANCELLED, InterviewScheduleStatus.COMPLETED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Interview cannot be cancelled in its current state.")

    if interview.calendar_event_id:
        CalendarServiceFactory.get_service().cancel_calendar_event(interview.calendar_event_id)

    interview.status = InterviewScheduleStatus.CANCELLED
    interview.cancelled_at = datetime.utcnow()
    interview.cancellation_reason = payload.reason.strip()
    interview.updated_at = datetime.utcnow()
    session.add(interview)
    session.commit()

    candidate = session.get(Candidate, interview.candidate_id)
    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    if candidate is not None:
        email_payload = generate_interview_cancellation_email(
            candidate_name=_candidate_name(candidate),
            job_title=job.title if job is not None else candidate.role_title,
            reason=payload.reason.strip(),
        )
        EmailService.send_email(
            candidate.email,
            email_payload["subject"],
            email_payload["body"],
            session=session,
            employee_id=None,
            notification_type="interview_booking_cancelled",
        )

    return {"message": "Interview cancelled and candidate notified."}


@router.post(
    "/admin/interviews/{interview_id}/reschedule",
    response_model=InterviewBookingRequestCreateResponse,
)
def reschedule_interview(
    interview_id: int,
    payload: InterviewRescheduleRequest,
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> InterviewBookingRequestCreateResponse:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")

    candidate = session.get(Candidate, interview.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    if interview.status == InterviewScheduleStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completed interviews cannot be rescheduled.")

    if interview.calendar_event_id:
        CalendarServiceFactory.get_service().cancel_calendar_event(interview.calendar_event_id)

    interview.booking_token = str(uuid4())
    interview.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, settings.booking_token_expiry_hours))
    interview.proposed_slots = _serialize_slots(payload.new_proposed_slots)
    interview.selected_slot_start = None
    interview.selected_slot_end = None
    interview.calendar_event_id = None
    interview.meet_link = None
    interview.booked_at = None
    interview.cancelled_at = None
    interview.cancellation_reason = ""
    interview.status = InterviewScheduleStatus.RESCHEDULED
    interview.updated_at = datetime.utcnow()

    if payload.format is not None and payload.format.strip():
        interview.format = payload.format.strip()
    if payload.location_or_link is not None:
        interview.location_or_link = payload.location_or_link.strip()
    if payload.interviewer_ids is not None:
        interview.interviewer_ids = sorted({int(item) for item in payload.interviewer_ids if int(item) > 0})
    if payload.notes is not None:
        interview.notes = payload.notes.strip()

    session.add(interview)
    session.commit()

    booking_url = _booking_url(interview.booking_token)
    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title
    email_payload = generate_interview_self_scheduling_email(
        candidate_name=_candidate_name(candidate),
        job_title=job_title,
        interview_format=interview.format,
        booking_url=booking_url,
        booking_deadline=interview.token_expires_at,
        additional_notes=interview.notes,
    )
    email_sent = EmailService.send_email(
        candidate.email,
        email_payload["subject"],
        email_payload["body"],
        session=session,
        employee_id=None,
        notification_type="interview_booking_rescheduled",
    )

    if email_sent:
        candidate.interview_email_sent = True
        candidate.interview_email_sent_at = datetime.utcnow()
        session.add(candidate)
        session.commit()

    return InterviewBookingRequestCreateResponse(
        interview_id=int(interview.interview_id),
        booking_token=interview.booking_token,
        booking_url=booking_url,
        token_expires_at=interview.token_expires_at,
        email_subject=email_payload["subject"],
        email_body=email_payload["body"],
        email_sent=email_sent,
    )


@router.post("/admin/interviews/{interview_id}/resend-invite", response_model=InterviewBookingRequestCreateResponse)
def resend_interview_invite(
    interview_id: int,
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> InterviewBookingRequestCreateResponse:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")

    if interview.status in {InterviewScheduleStatus.CANCELLED, InterviewScheduleStatus.COMPLETED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invite cannot be resent for this interview.")

    candidate = session.get(Candidate, interview.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    interview.booking_token = str(uuid4())
    interview.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=max(1, settings.booking_token_expiry_hours))
    interview.status = InterviewScheduleStatus.PENDING_BOOKING
    interview.updated_at = datetime.utcnow()
    session.add(interview)
    session.commit()

    booking_url = _booking_url(interview.booking_token)
    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title
    email_payload = generate_interview_self_scheduling_email(
        candidate_name=_candidate_name(candidate),
        job_title=job_title,
        interview_format=interview.format,
        booking_url=booking_url,
        booking_deadline=interview.token_expires_at,
        additional_notes=interview.notes,
    )

    email_sent = EmailService.send_email(
        candidate.email,
        email_payload["subject"],
        email_payload["body"],
        session=session,
        employee_id=None,
        notification_type="interview_booking_invite_resend",
    )

    return InterviewBookingRequestCreateResponse(
        interview_id=int(interview.interview_id),
        booking_token=interview.booking_token,
        booking_url=booking_url,
        token_expires_at=interview.token_expires_at,
        email_subject=email_payload["subject"],
        email_body=email_payload["body"],
        email_sent=email_sent,
    )


@router.post("/admin/interviews/{interview_id}/complete")
def mark_interview_completed(
    interview_id: int,
    _: User = Depends(_require_admin_or_manager),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    interview = session.get(Interview, interview_id)
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found.")

    if interview.status not in {InterviewScheduleStatus.BOOKED, InterviewScheduleStatus.RESCHEDULED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only booked interviews can be marked completed.")

    interview.status = InterviewScheduleStatus.COMPLETED
    interview.updated_at = datetime.utcnow()
    session.add(interview)
    session.commit()
    return {"message": "Interview marked as completed."}


@router.get("/interviews/booking/{booking_token}", response_model=InterviewBookingPortalRead)
def get_booking_portal(
    booking_token: str,
    session: Session = Depends(get_session),
) -> InterviewBookingPortalRead:
    interview = session.exec(select(Interview).where(Interview.booking_token == booking_token)).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking link not found.")

    if _refresh_expired_status(interview):
        session.add(interview)
        session.commit()

    candidate = session.get(Candidate, interview.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate record no longer exists.")

    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title

    slots = _deserialize_slots(interview.proposed_slots)
    slot_reads = [
        _to_slot_read(slot.start, slot.end, slot_id=f"{int(slot.start.timestamp())}-{int(slot.end.timestamp())}")
        for slot in slots
    ]

    return InterviewBookingPortalRead(
        interview_id=int(interview.interview_id),
        candidate_name=_candidate_name(candidate),
        candidate_email=candidate.email,
        job_title=job_title,
        format=interview.format,
        location_or_link=interview.location_or_link,
        proposed_slots=slot_reads,
        selected_slot_start=interview.selected_slot_start,
        selected_slot_end=interview.selected_slot_end,
        token_expires_at=interview.token_expires_at,
        status=interview.status,
        meet_link=interview.meet_link,
    )


@router.post("/interviews/booking/{booking_token}/confirm", response_model=InterviewBookingConfirmResponse)
def confirm_booking_slot(
    booking_token: str,
    payload: InterviewBookingConfirmRequest,
    session: Session = Depends(get_session),
) -> InterviewBookingConfirmResponse:
    interview = session.exec(select(Interview).where(Interview.booking_token == booking_token)).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking link not found.")

    if _refresh_expired_status(interview):
        session.add(interview)
        session.commit()

    if interview.status == InterviewScheduleStatus.EXPIRED:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This scheduling link has expired.")
    if interview.status == InterviewScheduleStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This interview request has been cancelled.")
    if interview.status == InterviewScheduleStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This interview has already been completed.")
    if interview.status == InterviewScheduleStatus.BOOKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This interview slot is already booked.")

    candidate = session.get(Candidate, interview.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title

    selected_start = _as_utc(payload.selected_slot_start)
    selected_end = _as_utc(payload.selected_slot_end)
    if selected_end <= selected_start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected slot end must be after start.")

    proposed_slots = _deserialize_slots(interview.proposed_slots)
    if not _slot_matches(proposed_slots, selected_start, selected_end):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected slot is not one of the proposed options.")

    attendee_emails, interviewer_emails = _collect_emails(candidate, interview.interviewer_ids or [], session)
    requires_virtual_link = "meet" in interview.format.lower() or "teams" in interview.format.lower()
    calendar_payload = CalendarServiceFactory.get_service().create_calendar_event(
        title=f"Interview: {_candidate_name(candidate)} - {job_title}",
        description=(
            f"Interview for {job_title}.\n"
            f"Candidate: {_candidate_name(candidate)} ({candidate.email})\n"
            f"Format: {interview.format}\n"
            f"Notes: {interview.notes or 'N/A'}"
        ),
        start_datetime=selected_start,
        end_datetime=selected_end,
        attendee_emails=attendee_emails,
        location_or_link=interview.location_or_link,
        meet_link=requires_virtual_link,
    )

    event_id = str(calendar_payload.get("event_id", "")).strip() or None
    meet_link = str(calendar_payload.get("google_meet_link", "")).strip() or None

    interview.status = InterviewScheduleStatus.BOOKED
    interview.selected_slot_start = selected_start
    interview.selected_slot_end = selected_end
    interview.booked_at = datetime.utcnow()
    interview.calendar_event_id = event_id
    interview.meet_link = meet_link
    interview.updated_at = datetime.utcnow()

    candidate.status = CandidateStatus.INTERVIEW_SCHEDULED
    candidate.interview_date = selected_start.date()

    session.add(interview)
    session.add(candidate)
    session.commit()

    resolved_location = _event_location(interview, meet_link)
    candidate_confirmation_email = generate_interview_booking_confirmation_email(
        recipient_name=_candidate_name(candidate),
        job_title=job_title,
        start_at=selected_start,
        end_at=selected_end,
        interview_format=interview.format,
        location_or_link=resolved_location,
        is_candidate=True,
    )
    EmailService.send_email(
        candidate.email,
        candidate_confirmation_email["subject"],
        candidate_confirmation_email["body"],
        session=session,
        employee_id=None,
        notification_type="interview_booking_confirmed_candidate",
    )

    for email in interviewer_emails:
        interviewer_email_payload = generate_interview_booking_confirmation_email(
            recipient_name="Interviewer",
            job_title=job_title,
            start_at=selected_start,
            end_at=selected_end,
            interview_format=interview.format,
            location_or_link=resolved_location,
            is_candidate=False,
        )
        EmailService.send_email(
            email,
            interviewer_email_payload["subject"],
            interviewer_email_payload["body"],
            session=session,
            employee_id=None,
            notification_type="interview_booking_confirmed_interviewer",
        )

    hr_email = settings.email_from_address.strip()
    if hr_email and hr_email.lower() not in {candidate.email.lower(), *(email.lower() for email in interviewer_emails)}:
        hr_subject = f"Interview booked: {_candidate_name(candidate)} for {job_title}"
        hr_body = (
            f"Candidate {_candidate_name(candidate)} selected a slot for {job_title}.\n"
            f"Start (UTC): {selected_start.isoformat()}\n"
            f"End (UTC): {selected_end.isoformat()}\n"
            f"Format: {interview.format}\n"
            f"Join details: {resolved_location or 'TBD'}"
        )
        EmailService.send_email(
            hr_email,
            hr_subject,
            hr_body,
            session=session,
            employee_id=None,
            notification_type="interview_booking_confirmed_hr",
        )

    calendar_title = f"Interview - {job_title}"
    calendar_details = (
        f"Candidate: {_candidate_name(candidate)} ({candidate.email})\n"
        f"Format: {interview.format}\n"
        f"Notes: {interview.notes or 'N/A'}"
    )

    return InterviewBookingConfirmResponse(
        message="Interview confirmed successfully.",
        interview_id=int(interview.interview_id),
        status=InterviewScheduleStatus.BOOKED,
        selected_slot_start=selected_start,
        selected_slot_end=selected_end,
        format=interview.format,
        meet_link=resolved_location or None,
        candidate_email=candidate.email,
        google_calendar_url=_google_calendar_url(
            calendar_title,
            calendar_details,
            resolved_location,
            selected_start,
            selected_end,
        ),
        outlook_calendar_url=_outlook_calendar_url(
            calendar_title,
            calendar_details,
            resolved_location,
            selected_start,
            selected_end,
        ),
        ics_download_url=f"/api/interviews/booking/{booking_token}/calendar.ics",
    )


@router.get("/interviews/booking/{booking_token}/calendar.ics")
def download_booking_ics(
    booking_token: str,
    session: Session = Depends(get_session),
) -> Response:
    interview = session.exec(select(Interview).where(Interview.booking_token == booking_token)).first()
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking link not found.")

    if interview.status not in {InterviewScheduleStatus.BOOKED, InterviewScheduleStatus.COMPLETED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Calendar file is available only after booking.")

    candidate = session.get(Candidate, interview.candidate_id)
    if candidate is None or interview.selected_slot_start is None or interview.selected_slot_end is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview details are unavailable.")

    job = session.get(Job, interview.job_id) if interview.job_id is not None else None
    job_title = job.title if job is not None else candidate.role_title

    def _ics_ts(value: datetime) -> str:
        return _as_utc(value).strftime("%Y%m%dT%H%M%SZ")

    uid = interview.calendar_event_id or f"interview-{interview.interview_id}@talent-spark"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Talent Spark//Interview Scheduling//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_ics_ts(datetime.now(timezone.utc))}",
        f"DTSTART:{_ics_ts(interview.selected_slot_start)}",
        f"DTEND:{_ics_ts(interview.selected_slot_end)}",
        f"SUMMARY:Interview - {job_title}",
        f"DESCRIPTION:Candidate {_candidate_name(candidate)} ({candidate.email})",
        f"LOCATION:{(interview.meet_link or interview.location_or_link or '').strip()}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    content = "\r\n".join(lines)
    filename = f"interview-{interview.interview_id}.ics"
    return Response(
        content=content,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
