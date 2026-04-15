from __future__ import annotations

from datetime import date
import json
import logging
from typing import Any
from urllib import error, request

from backend.app.core.config import settings


logger = logging.getLogger(__name__)


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    for item in payload.get("output", []):
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value.strip()

    raise ValueError("No text output found in OpenAI response.")


def _call_openai_email_json(*, prompt: str) -> dict[str, str]:
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    payload = {
        "model": settings.openai_email_model,
        "input": [
            {
                "role": "developer",
                "content": (
                    "You are a senior HR communications specialist. "
                    "Write concise, professional, warm emails. Return strict JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_output_tokens": 1000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "email_payload",
                "schema": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["subject", "body"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
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
        body_text = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI email generation failed with status {exc.code}: {body_text}") from exc

    parsed = json.loads(_extract_response_text(response_payload))
    return {
        "subject": str(parsed.get("subject", "")).strip(),
        "body": str(parsed.get("body", "")).strip(),
    }


def _safe_generate(*, prompt: str, fallback_subject: str, fallback_body: str) -> dict[str, str]:
    try:
        generated = _call_openai_email_json(prompt=prompt)
        if generated["subject"] and generated["body"]:
            return generated
    except Exception:
        logger.exception("AI email generation failed. Falling back to template.")

    return {
        "subject": fallback_subject,
        "body": fallback_body.strip(),
    }


def generate_welcome_email(
    *,
    full_name: str,
    designation: str,
    department: str,
    start_date: date,
) -> dict[str, str]:
    company_name = settings.company_name
    prompt = (
        f"Write a professional and warm welcome email for a new employee joining {company_name}.\n"
        f"Employee Name: {full_name}\n"
        f"Designation: {designation}\n"
        f"Department: {department}\n"
        f"Start Date: {start_date.isoformat()}\n"
        f"Include instructions to visit {settings.signup_url} to set their password and activate their account.\n"
        "Keep it concise, friendly, and professional.\n"
        "Also generate a suitable email subject line.\n"
        "Return JSON with keys subject and body."
    )
    fallback_subject = f"Welcome to {company_name} - Activate Your Account"
    fallback_body = (
        f"Hi {full_name},\n\n"
        f"Welcome to {company_name}. We are excited to have you join us as {designation} in the {department} team. "
        f"Your start date is {start_date.isoformat()}.\n\n"
        f"Please activate your account by visiting {settings.signup_url} and setting your password.\n\n"
        "If you need any help, reply to this email and our HR team will assist you.\n\n"
        f"Best regards,\n{settings.email_from_name}"
    )
    return _safe_generate(prompt=prompt, fallback_subject=fallback_subject, fallback_body=fallback_body)


def generate_interview_invitation_email(
    *,
    candidate_name: str,
    job_title: str,
    interview_date: date,
    interview_time: str,
    interview_format: str,
    location_or_link: str,
    additional_notes: str,
) -> dict[str, str]:
    company_name = settings.company_name
    prompt = (
        f"You are an HR professional at {company_name}.\n"
        "Write a formal, warm, and encouraging interview invitation email to a job candidate with the following details:\n\n"
        f"Candidate Name: {candidate_name}\n"
        f"Job Applied For: {job_title}\n"
        f"Interview Date: {interview_date.isoformat()}\n"
        f"Interview Time: {interview_time}\n"
        f"Interview Format: {interview_format}\n"
        f"Location / Link: {location_or_link}\n"
        f"Additional Notes: {additional_notes or 'None'}\n\n"
        "The email should:\n"
        "- Open with congratulating the candidate on being shortlisted after the initial screening\n"
        "- Clearly state the interview date, time, format, and location/link\n"
        "- Mention what to expect (a conversation about their background, skills, and experience relevant to the role)\n"
        "- Invite them to confirm attendance by replying to the email\n"
        "- End with a professional and encouraging sign-off\n"
        "- Be concise (under 300 words)\n\n"
        "Also generate a suitable subject line. Return JSON with keys subject and body."
    )
    fallback_subject = f"Interview Invitation - {job_title}"
    fallback_body = (
        f"Dear {candidate_name},\n\n"
        f"Congratulations. You have been shortlisted for the {job_title} role at {company_name}.\n\n"
        f"Interview details:\n"
        f"Date: {interview_date.isoformat()}\n"
        f"Time: {interview_time}\n"
        f"Format: {interview_format}\n"
        f"Location/Link: {location_or_link}\n\n"
        "The interview will focus on your background, skills, and experience relevant to the role. "
        "Please confirm your availability by replying to this email.\n\n"
        f"Additional Notes: {additional_notes or 'N/A'}\n\n"
        f"Best regards,\n{settings.email_from_name}"
    )
    return _safe_generate(prompt=prompt, fallback_subject=fallback_subject, fallback_body=fallback_body)


def generate_leave_approval_email(
    *,
    full_name: str,
    department: str,
    leave_type: str,
    start_date: date,
    end_date: date,
    total_days: int,
    reason: str,
) -> dict[str, str]:
    company_name = settings.company_name
    prompt = (
        f"You are an HR professional at {company_name}.\n"
        "Write a formal and warm leave approval email to an employee.\n\n"
        f"Employee Name: {full_name}\n"
        f"Department: {department}\n"
        f"Leave Type: {leave_type}\n"
        f"Leave Duration: {start_date.isoformat()} to {end_date.isoformat()} ({total_days} days)\n"
        f"Reason Provided: {reason}\n\n"
        "The email should:\n"
        "- Confirm that their leave request has been officially approved\n"
        "- State the exact dates of the approved leave\n"
        "- Wish them well\n"
        "- Remind them to hand over responsibilities before leaving if applicable\n"
        "- Include a professional sign-off from the HR department\n"
        "- Be concise (under 200 words)\n\n"
        "Also generate a suitable subject line. Return JSON with keys subject and body."
    )
    fallback_subject = f"Leave Request Approved ({start_date.isoformat()} - {end_date.isoformat()})"
    fallback_body = (
        f"Hi {full_name},\n\n"
        f"Your {leave_type} leave request has been approved for {start_date.isoformat()} to {end_date.isoformat()} "
        f"({total_days} days).\n\n"
        "Please ensure responsibilities are handed over before your leave begins, where applicable.\n"
        "We hope you have a restful and smooth time away.\n\n"
        f"Best regards,\n{settings.email_from_name}"
    )
    return _safe_generate(prompt=prompt, fallback_subject=fallback_subject, fallback_body=fallback_body)


def generate_leave_rejection_email(
    *,
    full_name: str,
    department: str,
    leave_type: str,
    start_date: date,
    end_date: date,
    total_days: int,
    hr_note: str,
) -> dict[str, str]:
    company_name = settings.company_name
    prompt = (
        f"You are an HR professional at {company_name}.\n"
        "Write a formal, empathetic, and respectful leave rejection email to an employee.\n\n"
        f"Employee Name: {full_name}\n"
        f"Department: {department}\n"
        f"Leave Type: {leave_type}\n"
        f"Requested Dates: {start_date.isoformat()} to {end_date.isoformat()} ({total_days} days)\n"
        f"Reason for Rejection: {hr_note}\n\n"
        "The email should:\n"
        "- Acknowledge that the request was received and reviewed\n"
        "- Inform them politely that it cannot be approved right now\n"
        "- Clearly but sensitively state the reason\n"
        "- Encourage them to reapply for a more suitable date or speak with HR\n"
        "- End with an empathetic and supportive sign-off\n"
        "- Be concise (under 200 words)\n\n"
        "Also generate a suitable subject line. Return JSON with keys subject and body."
    )
    fallback_subject = "Update on Your Leave Request"
    fallback_body = (
        f"Hi {full_name},\n\n"
        f"Thank you for submitting your {leave_type} leave request for {start_date.isoformat()} to {end_date.isoformat()} "
        f"({total_days} days). After review, we are unable to approve this request at this time.\n\n"
        f"Reason: {hr_note}\n\n"
        "Please feel free to submit a revised request for different dates or contact HR if you would like to discuss this further.\n\n"
        f"Best regards,\n{settings.email_from_name}"
    )
    return _safe_generate(prompt=prompt, fallback_subject=fallback_subject, fallback_body=fallback_body)
