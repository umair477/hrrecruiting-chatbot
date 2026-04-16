from __future__ import annotations

import ast
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib import error, request

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Employee, LeaveQuota, LeaveRequest, LeaveStatus, LeaveType


logger = logging.getLogger(__name__)

_LEAVE_SUBMISSION_PATTERN = re.compile(
    r"<<<LEAVE_SUBMISSION>>>\s*(?P<payload>\{.*?\})\s*<<<END_SUBMISSION>>>",
    re.DOTALL,
)
_DEFAULT_ANNUAL_TOTAL = 20
_DEFAULT_SICK_TOTAL = 10
_DEFAULT_CASUAL_TOTAL = 5


def normalize_leave_chat_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in history:
        role_raw = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        role = "assistant" if role_raw in {"assistant", "bot", "ai"} else "user"
        normalized.append({"role": role, "content": content})
    return normalized[-30:]


def coerce_leave_type(value: str | LeaveType) -> LeaveType:
    if isinstance(value, LeaveType):
        return value

    normalized = str(value).strip().lower()
    mapping = {
        "annual": LeaveType.ANNUAL,
        "sick": LeaveType.SICK,
        "casual": LeaveType.CASUAL,
        "unpaid": LeaveType.UNPAID,
    }
    leave_type = mapping.get(normalized)
    if leave_type is None:
        raise ValueError("Leave type must be one of Annual, Sick, Casual, or Unpaid.")
    return leave_type


def count_working_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    total = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            total += 1
        cursor += timedelta(days=1)
    return total


def get_or_create_leave_quota(session: Session, employee_id: int, year: int | None = None) -> LeaveQuota:
    target_year = year or datetime.utcnow().year
    quota = session.exec(
        select(LeaveQuota).where(LeaveQuota.employee_id == employee_id, LeaveQuota.year == target_year)
    ).first()
    if quota is not None:
        return quota

    quota = LeaveQuota(
        employee_id=employee_id,
        year=target_year,
        annual_total=_DEFAULT_ANNUAL_TOTAL,
        annual_used=0,
        sick_total=_DEFAULT_SICK_TOTAL,
        sick_used=0,
        casual_total=_DEFAULT_CASUAL_TOTAL,
        casual_used=0,
        unpaid_used=0,
    )
    session.add(quota)
    session.commit()
    session.refresh(quota)
    return quota


def _remaining_for_leave_type(quota: LeaveQuota, leave_type: LeaveType) -> int | None:
    if leave_type == LeaveType.ANNUAL:
        return max(int(quota.annual_total) - int(quota.annual_used), 0)
    if leave_type == LeaveType.SICK:
        return max(int(quota.sick_total) - int(quota.sick_used), 0)
    if leave_type == LeaveType.CASUAL:
        return max(int(quota.casual_total) - int(quota.casual_used), 0)
    return None


def _increment_used_quota(quota: LeaveQuota, leave_type: LeaveType, days: int) -> None:
    if leave_type == LeaveType.ANNUAL:
        quota.annual_used = int(quota.annual_used) + days
    elif leave_type == LeaveType.SICK:
        quota.sick_used = int(quota.sick_used) + days
    elif leave_type == LeaveType.CASUAL:
        quota.casual_used = int(quota.casual_used) + days
    else:
        quota.unpaid_used = int(quota.unpaid_used) + days


def get_employee_leave_quota_summary(session: Session, employee_id: int, year: int | None = None) -> dict[str, int]:
    quota = get_or_create_leave_quota(session, employee_id, year)
    return {
        "annual_total": int(quota.annual_total),
        "annual_remaining": max(int(quota.annual_total) - int(quota.annual_used), 0),
        "sick_total": int(quota.sick_total),
        "sick_remaining": max(int(quota.sick_total) - int(quota.sick_used), 0),
        "casual_total": int(quota.casual_total),
        "casual_remaining": max(int(quota.casual_total) - int(quota.casual_used), 0),
        "unpaid_used": int(quota.unpaid_used),
    }


def list_employee_leave_history(session: Session, employee_id: int) -> list[LeaveRequest]:
    return session.exec(
        select(LeaveRequest)
        .where(LeaveRequest.employee_id == employee_id)
        .order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.created_at.desc())
    ).all()


def list_employee_pending_or_approved_leaves(session: Session, employee_id: int) -> list[LeaveRequest]:
    tracked_statuses = [LeaveStatus.PENDING, LeaveStatus.APPROVED]
    return session.exec(
        select(LeaveRequest)
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(tracked_statuses),
        )
        .order_by(LeaveRequest.start_date.asc())
    ).all()


def check_leave_overlap(
    existing_requests: list[LeaveRequest],
    start_date: date,
    end_date: date,
) -> LeaveRequest | None:
    for leave_request in existing_requests:
        if start_date <= leave_request.end_date and end_date >= leave_request.start_date:
            return leave_request
    return None


def submit_employee_leave_request(
    *,
    session: Session,
    employee_id: int,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    reason: str,
) -> LeaveRequest:
    if end_date < start_date:
        raise ValueError("End date must be on or after the start date.")

    requested_days = count_working_days(start_date, end_date)
    if requested_days <= 0:
        raise ValueError("The selected range has no working days. Please choose weekdays.")

    existing_requests = list_employee_pending_or_approved_leaves(session, employee_id)
    overlapping_request = check_leave_overlap(existing_requests, start_date, end_date)
    if overlapping_request is not None:
        raise ValueError(
            "These dates overlap an existing "
            f"{overlapping_request.status.value} request from "
            f"{overlapping_request.start_date.isoformat()} to {overlapping_request.end_date.isoformat()}."
        )

    quota = get_or_create_leave_quota(session, employee_id)
    remaining_days = _remaining_for_leave_type(quota, leave_type)
    if remaining_days is not None and requested_days > remaining_days:
        raise ValueError(
            f"Insufficient {leave_type.value.lower()} leave quota. Remaining: {remaining_days} day(s), requested: {requested_days} day(s)."
        )

    leave_request = LeaveRequest(
        employee_id=employee_id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        total_days=requested_days,
        reason=reason.strip(),
        status=LeaveStatus.PENDING,
        submitted_at=datetime.utcnow(),
    )
    _increment_used_quota(quota, leave_type, requested_days)
    session.add(quota)
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    return leave_request


def _build_system_prompt(
    *,
    employee: Employee,
    quota_summary: dict[str, int],
    existing_requests: list[LeaveRequest],
) -> str:
    existing_lines = [
        (
            f"- {leave.leave_type.value}, {leave.start_date.isoformat()}, "
            f"{leave.end_date.isoformat()}, {leave.status.value}"
        )
        for leave in existing_requests
    ]
    existing_text = "\n".join(existing_lines) if existing_lines else "- None"

    return (
        "You are an intelligent, empathetic HR Leave Assistant for Talent Spark.\n"
        f"You are helping an employee named {(employee.full_name or employee.name).strip()} "
        f"from the {employee.department.strip() or 'General'} department.\n\n"
        "CURRENT LEAVE BALANCES FOR THIS EMPLOYEE:\n"
        f"- Annual Leave:  {quota_summary['annual_remaining']} days remaining out of {quota_summary['annual_total']}\n"
        f"- Sick Leave:    {quota_summary['sick_remaining']} days remaining out of {quota_summary['sick_total']}\n"
        f"- Casual Leave:  {quota_summary['casual_remaining']} days remaining out of {quota_summary['casual_total']}\n"
        "- Unpaid Leave:  Unlimited (always available)\n\n"
        "EMPLOYEE'S EXISTING LEAVE REQUESTS (Pending or Approved):\n"
        f"{existing_text}\n"
        "(Use this to detect scheduling conflicts)\n\n"
        "YOUR RESPONSIBILITIES:\n"
        "1. Greet the employee warmly on the first message.\n"
        "2. If the employee wants to request leave, collect the following naturally through conversation (do NOT ask all at once):\n"
        "   - Leave type (Annual / Sick / Casual / Unpaid)\n"
        "   - Start date\n"
        "   - End date\n"
        "   - Reason for leave\n"
        "3. Once you have all details, calculate the number of working days and show a confirmation summary before submitting.\n"
        "4. Before confirming, check:\n"
        "   - Does the employee have sufficient quota for the leave type?\n"
        "   - Do the dates overlap with any existing pending/approved leave?\n"
        "   If quota is insufficient, suggest alternatives (different leave type, shorter duration, or unpaid leave for excess days).\n"
        "   If there is a conflict, inform the employee and ask for new dates.\n"
        "5. If the employee asks about their leave balance, respond with the exact figures provided above.\n"
        "6. If the employee asks about the status of a previous leave, refer to the existing leave requests listed above.\n"
        "7. If the employee's message is unclear or off-topic, politely redirect them to leave-related topics.\n"
        "8. Always respond in a professional, friendly, and concise tone.\n\n"
        "IMPORTANT — STRUCTURED SUBMISSION SIGNAL:\n"
        "When the employee confirms they want to submit the leave request, your response MUST end with this exact JSON block "
        "(after your conversational message) so the backend can parse and store it:\n\n"
        "<<<LEAVE_SUBMISSION>>>\n"
        "{\n"
        "  'leave_type': 'Annual' | 'Sick' | 'Casual' | 'Unpaid',\n"
        "  'start_date': 'YYYY-MM-DD',\n"
        "  'end_date': 'YYYY-MM-DD',\n"
        "  'total_days': <integer>,\n"
        "  'reason': '<reason text>'\n"
        "}\n"
        "<<<END_SUBMISSION>>>\n\n"
        "If the employee has NOT yet confirmed or if details are still missing, do NOT include the JSON block. "
        "Only include it once the employee explicitly says Yes / Confirm / Submit or equivalent."
    )


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    output = payload.get("output", [])
    for item in output:
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value.strip()

    raise ValueError("No text output found in OpenAI leave chat response.")


def _generate_leave_reply(*, system_prompt: str, messages: list[dict[str, str]]) -> str:
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for employee leave chat.")

    payload = {
        "model": settings.openai_leave_chat_model,
        "input": [
            {"role": "developer", "content": system_prompt},
            *messages,
        ],
    }
    http_request = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=45) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI leave chat request failed with status {exc.code}: {body}") from exc

    return _extract_response_text(response_payload)


def _extract_submission(reply: str) -> tuple[str, dict[str, Any] | None]:
    match = _LEAVE_SUBMISSION_PATTERN.search(reply)
    if match is None:
        return reply.strip(), None

    payload_block = match.group("payload").strip()
    cleaned_reply = _LEAVE_SUBMISSION_PATTERN.sub("", reply).strip()

    parsed_payload: dict[str, Any] | None = None
    try:
        candidate = json.loads(payload_block)
        if isinstance(candidate, dict):
            parsed_payload = candidate
    except json.JSONDecodeError:
        try:
            candidate = ast.literal_eval(payload_block)
            if isinstance(candidate, dict):
                parsed_payload = candidate
        except (SyntaxError, ValueError):
            parsed_payload = None

    return cleaned_reply, parsed_payload


def _parse_submission_payload(payload: dict[str, Any]) -> tuple[LeaveType, date, date, str]:
    leave_type = coerce_leave_type(str(payload.get("leave_type", "")))
    start_date_raw = str(payload.get("start_date", "")).strip()
    end_date_raw = str(payload.get("end_date", "")).strip()
    reason = str(payload.get("reason", "")).strip()

    if not start_date_raw or not end_date_raw:
        raise ValueError("Start date and end date are required.")
    try:
        start_date = date.fromisoformat(start_date_raw)
        end_date = date.fromisoformat(end_date_raw)
    except ValueError as exc:
        raise ValueError("Dates must be in YYYY-MM-DD format.") from exc

    if not reason:
        raise ValueError("Reason is required before submission.")

    return leave_type, start_date, end_date, reason


def run_employee_leave_chat_turn(
    *,
    session: Session,
    employee: Employee,
    message: str,
    conversation_history: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    normalized_history = normalize_leave_chat_history(conversation_history)
    existing_requests = list_employee_pending_or_approved_leaves(session, int(employee.id))
    quota_summary = get_employee_leave_quota_summary(session, int(employee.id))
    system_prompt = _build_system_prompt(
        employee=employee,
        quota_summary=quota_summary,
        existing_requests=existing_requests,
    )

    messages = [*normalized_history, {"role": "user", "content": message.strip()}]
    ai_reply = _generate_leave_reply(system_prompt=system_prompt, messages=messages)
    cleaned_reply, submission_payload = _extract_submission(ai_reply)
    final_reply = cleaned_reply or ai_reply.strip()

    if submission_payload is not None:
        try:
            leave_type, start_date, end_date, reason = _parse_submission_payload(submission_payload)
            created_leave = submit_employee_leave_request(
                session=session,
                employee_id=int(employee.id),
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                reason=reason,
            )
            success_message = f"✅ Your leave request has been submitted! Reference ID: {created_leave.id}"
            final_reply = f"{final_reply}\n\n{success_message}".strip()
        except ValueError as exc:
            conflict_message = (
                "It looks like there was a conflict at submission time. "
                f"{exc} Please adjust your request."
            )
            final_reply = f"{final_reply}\n\n{conflict_message}".strip()
        except Exception:
            logger.exception("Leave chat submission failed after extracting structured payload.")
            conflict_message = (
                "It looks like there was a conflict at submission time. "
                "An unexpected server error occurred. Please adjust your request."
            )
            final_reply = f"{final_reply}\n\n{conflict_message}".strip()

    updated_history = [
        *normalized_history,
        {"role": "user", "content": message.strip()},
        {"role": "assistant", "content": final_reply},
    ]
    return final_reply, updated_history
