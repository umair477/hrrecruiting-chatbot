from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
import re
from typing import Any, Callable, Optional


class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PrivacyAlert:
    contains_sensitive_medical_detail: bool
    matched_terms: list[str] = field(default_factory=list)
    employee_message: Optional[str] = None
    safe_reason_summary: Optional[str] = None


@dataclass
class LeaveBalanceResult:
    has_balance: bool
    remaining_days: Optional[float] = None
    note: str = ""


@dataclass
class LeaveRequestDraft:
    employee_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    reason_summary: Optional[str] = None
    handover_contact: Optional[str] = None
    handover_plan: Optional[str] = None
    urgency_level: Optional[UrgencyLevel] = None
    urgent_project_deadline: Optional[bool] = None
    privacy_flagged: bool = False
    balance_checked: bool = False
    balance_status: Optional[LeaveBalanceResult] = None
    submitted_to_hr: bool = False
    chat_transcript: list[dict[str, str]] = field(default_factory=list)

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "reason_summary": self.reason_summary,
            "handover_contact": self.handover_contact,
            "handover_plan": self.handover_plan,
            "urgency_level": self.urgency_level.value if self.urgency_level else None,
            "urgent_project_deadline": self.urgent_project_deadline,
            "privacy_flagged": self.privacy_flagged,
            "balance_checked": self.balance_checked,
            "balance_status": asdict(self.balance_status) if self.balance_status else None,
            "submitted_to_hr": self.submitted_to_hr,
            "chat_transcript": list(self.chat_transcript),
        }

    @classmethod
    def from_checkpoint(cls, payload: dict[str, Any]) -> "LeaveRequestDraft":
        urgency_level = payload.get("urgency_level")
        balance_status = payload.get("balance_status")
        transcript = payload.get("chat_transcript", [])
        return cls(
            employee_id=str(payload["employee_id"]) if payload.get("employee_id") is not None else None,
            start_date=date.fromisoformat(str(payload["start_date"])) if payload.get("start_date") else None,
            end_date=date.fromisoformat(str(payload["end_date"])) if payload.get("end_date") else None,
            reason_summary=str(payload["reason_summary"]) if payload.get("reason_summary") else None,
            handover_contact=str(payload["handover_contact"]) if payload.get("handover_contact") else None,
            handover_plan=str(payload["handover_plan"]) if payload.get("handover_plan") else None,
            urgency_level=UrgencyLevel(str(urgency_level)) if urgency_level else None,
            urgent_project_deadline=payload.get("urgent_project_deadline"),
            privacy_flagged=bool(payload.get("privacy_flagged", False)),
            balance_checked=bool(payload.get("balance_checked", False)),
            balance_status=LeaveBalanceResult(**balance_status) if isinstance(balance_status, dict) else None,
            submitted_to_hr=bool(payload.get("submitted_to_hr", False)),
            chat_transcript=[
                {
                    "speaker": str(item.get("speaker", "")),
                    "message": str(item.get("message", "")),
                }
                for item in transcript
                if isinstance(item, dict)
            ],
        )

    def missing_slots(self) -> list[str]:
        missing: list[str] = []
        if self.start_date is None:
            missing.append("start_date")
        if self.end_date is None:
            missing.append("end_date")
        if not self.reason_summary:
            missing.append("reason_summary")
        if not self.handover_contact and not self.handover_plan:
            missing.append("handover_contact")
        if self.urgency_level is None:
            missing.append("urgency_level")
        return missing

    def is_complete(self) -> bool:
        return not self.missing_slots()


BalanceChecker = Callable[[LeaveRequestDraft], LeaveBalanceResult]

SENSITIVE_MEDICAL_TERMS = {
    "cancer",
    "depression",
    "anxiety",
    "pregnancy complication",
    "ivf",
    "hiv",
    "std",
    "stroke",
    "surgery",
    "diagnosis",
    "bipolar",
    "schizophrenia",
    "autism",
    "epilepsy",
    "chemotherapy",
    "medical certificate",
}

MONTH_LOOKUP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

WEEKDAY_LOOKUP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def privacy_filter(reason_text: str) -> PrivacyAlert:
    normalized = reason_text.strip().lower()
    matched_terms = sorted(term for term in SENSITIVE_MEDICAL_TERMS if term in normalized)
    if matched_terms:
        return PrivacyAlert(
            contains_sensitive_medical_detail=True,
            matched_terms=matched_terms,
            employee_message=(
                "I can note this as medical leave, but detailed medical diagnoses should "
                "only be shared with HR directly via secure email."
            ),
            safe_reason_summary="Medical leave requested. Detailed diagnosis omitted from chat log.",
        )

    return PrivacyAlert(
        contains_sensitive_medical_detail=False,
        matched_terms=[],
        employee_message=None,
        safe_reason_summary=reason_text.strip(),
    )


def parse_date_range(message: str, today: Optional[date] = None) -> tuple[Optional[date], Optional[date]]:
    today = today or date.today()
    normalized = message.lower()
    duration_match = re.search(r"\bfor\s+(\d+)\s+day(?:s)?\b", normalized)
    duration_days = int(duration_match.group(1)) if duration_match else None

    iso_hits = re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", normalized)
    if iso_hits:
        parsed = [date(int(year), int(month), int(day)) for year, month, day in iso_hits]
        if len(parsed) >= 2:
            return parsed[0], parsed[1]
        if duration_days and duration_days > 1:
            return parsed[0], parsed[0] + timedelta(days=duration_days - 1)
        return parsed[0], parsed[0]

    month_day_hits = re.findall(
        r"\b("
        + "|".join(MONTH_LOOKUP.keys())
        + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?\b",
        normalized,
    )
    if month_day_hits:
        parsed_dates: list[date] = []
        for month_name, day_value, year_value in month_day_hits:
            year = int(year_value) if year_value else today.year
            parsed_dates.append(date(year, MONTH_LOOKUP[month_name], int(day_value)))
        if len(parsed_dates) >= 2:
            return parsed_dates[0], parsed_dates[1]
        if duration_days and duration_days > 1:
            return parsed_dates[0], parsed_dates[0] + timedelta(days=duration_days - 1)
        return parsed_dates[0], parsed_dates[0]

    day_month_hits = re.findall(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+("
        + "|".join(MONTH_LOOKUP.keys())
        + r")(?:,\s*(\d{4}))?\b",
        normalized,
    )
    if day_month_hits:
        parsed_dates = []
        for day_value, month_name, year_value in day_month_hits:
            year = int(year_value) if year_value else today.year
            parsed_dates.append(date(year, MONTH_LOOKUP[month_name], int(day_value)))
        if len(parsed_dates) >= 2:
            return parsed_dates[0], parsed_dates[1]
        if duration_days and duration_days > 1:
            return parsed_dates[0], parsed_dates[0] + timedelta(days=duration_days - 1)
        return parsed_dates[0], parsed_dates[0]

    if "tomorrow" in normalized:
        target = today + timedelta(days=1)
        if duration_days and duration_days > 1:
            return target, target + timedelta(days=duration_days - 1)
        return target, target

    if "today" in normalized:
        if duration_days and duration_days > 1:
            return today, today + timedelta(days=duration_days - 1)
        return today, today

    next_weekday_match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", normalized)
    if next_weekday_match:
        weekday = WEEKDAY_LOOKUP[next_weekday_match.group(1)]
        delta = (weekday - today.weekday()) % 7 or 7
        target = today + timedelta(days=delta)
        if duration_days and duration_days > 1:
            return target, target + timedelta(days=duration_days - 1)
        return target, target

    weekday_match = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", normalized)
    if weekday_match:
        weekday = WEEKDAY_LOOKUP[weekday_match.group(1)]
        delta = (weekday - today.weekday()) % 7
        target = today + timedelta(days=delta)
        if duration_days and duration_days > 1:
            return target, target + timedelta(days=duration_days - 1)
        return target, target

    return None, None


def extract_reason(message: str, *, today: Optional[date] = None) -> Optional[str]:
    patterns = [
        r"\bit'?s for ([^.?!]+)",
        r"\bthe reason is ([^.?!]+)",
        r"\breason is ([^.?!]+)",
        r"\bbecause ([^.?!]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message.strip(), flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .")

    return extract_reason_from_followup(message, today=today)


def extract_reason_from_followup(message: str, *, today: Optional[date] = None) -> Optional[str]:
    clauses = [chunk.strip(" .") for chunk in re.split(r"[.?!;\n]+", message) if chunk.strip()]
    for clause in clauses:
        normalized = clause.lower()
        if parse_date_range(clause, today=today) != (None, None):
            continue

        contact, handover_plan = extract_handover(clause)
        if contact or handover_plan:
            continue

        urgency_level, urgent_deadline = extract_urgency(clause)
        if urgency_level or urgent_deadline is not None:
            continue

        if any(
            token in normalized
            for token in {
                "cover",
                "handover",
                "deadline",
                "urgent",
                "asap",
                "leave",
                "day off",
                "days leave",
                "apply",
                "request",
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            }
        ):
            continue

        cleaned = re.sub(
            r"^(?:the reason is|reason is|it(?:'s| is)|i need (?:leave|time off|a day off) (?:for|because))\s+",
            "",
            clause,
            flags=re.IGNORECASE,
        ).strip(" .")
        if cleaned:
            return cleaned

    return None


def extract_handover(message: str) -> tuple[Optional[str], Optional[str]]:
    normalized = message.lower().strip()
    if any(
        phrase in normalized
        for phrase in {
            "no handover needed",
            "no handover required",
            "no coverage needed",
            "no cover needed",
            "nothing pending",
            "no pending work",
            "already met the deadline",
            "met the deadline",
            "already delivered my work",
            "delivered my work",
            "completed my work",
            "finished my work",
            "wrapped up my work",
        }
    ):
        return None, message.strip()

    contact_patterns = [
        r"\b([a-z]+(?:\s+[a-z]+)*)\s+is covering\b",
        r"\bcover(?:ing)?\s+by\s+([a-z]+(?:\s+[a-z]+)*)\b",
        r"\b([a-z]+(?:\s+[a-z]+)*)\s+will cover\b",
    ]
    for pattern in contact_patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            contact = " ".join(part.capitalize() for part in match.group(1).strip().split())
            return contact, f"{contact} will provide coverage while the employee is away."

    if "cover" in message.lower():
        return None, message.strip()
    return None, None


def extract_urgency(message: str) -> tuple[Optional[UrgencyLevel], Optional[bool]]:
    normalized = message.lower()
    if any(
        phrase in normalized
        for phrase in {
            "already met the deadline",
            "met the deadline",
            "already delivered my work",
            "delivered my work",
            "completed my work",
            "finished my work",
            "no pending work",
            "nothing pending",
            "all tasks are complete",
        }
    ):
        return UrgencyLevel.LOW, False
    if any(signal in normalized for signal in {"critical", "urgent", "asap", "production issue"}):
        return UrgencyLevel.HIGH, True
    if any(signal in normalized for signal in {"normal", "not urgent", "no deadlines", "no urgent work"}):
        return UrgencyLevel.LOW, False
    if any(signal in normalized for signal in {"deadline", "launch", "release", "client meeting"}):
        return UrgencyLevel.HIGH, True
    if any(signal in normalized for signal in {"moderate", "medium"}):
        return UrgencyLevel.MEDIUM, None
    return None, None


def humanize_date(value: Optional[date]) -> str:
    if value is None:
        return "unknown"
    return value.strftime("%A, %b %d, %Y")


class LeaveInterviewEngine:
    """Slot-filling leave workflow with privacy filtering and validation hooks."""

    def __init__(self, *, today: Optional[date] = None, balance_checker: Optional[BalanceChecker] = None) -> None:
        self.today = today or date.today()
        self.balance_checker = balance_checker
        self.draft = LeaveRequestDraft()

    def export_state(self) -> dict[str, Any]:
        return {
            "today": self.today.isoformat(),
            "draft": self.draft.to_checkpoint(),
        }

    def restore_state(self, payload: dict[str, Any]) -> None:
        draft_payload = payload.get("draft") if isinstance(payload.get("draft"), dict) else payload
        if isinstance(draft_payload, dict):
            self.draft = LeaveRequestDraft.from_checkpoint(draft_payload)

    def handle_message(self, message: str, employee_id: Optional[str] = None) -> dict[str, object]:
        self.draft.chat_transcript.append({"speaker": "employee", "message": message})
        if employee_id:
            self.draft.employee_id = employee_id

        self._update_from_message(message)
        self._validate_dates()
        self._run_balance_check_if_ready()

        privacy_note = None
        if self.draft.is_complete() and not self.draft.submitted_to_hr:
            self.draft.submitted_to_hr = True
            bot_message = "Thanks. I have everything needed and have prepared your request for HR review."
        else:
            bot_message = self._next_prompt()

        if self.draft.privacy_flagged:
            privacy_note = (
                "Detailed medical diagnoses should only be shared with HR directly via secure email."
            )

        self.draft.chat_transcript.append({"speaker": "bot", "message": bot_message})
        return {
            "reply": bot_message,
            "privacy_note": privacy_note,
            "missing_slots": self.draft.missing_slots(),
            "structured_report": self.build_hr_report() if self.draft.submitted_to_hr else None,
        }

    def build_hr_report(self) -> dict[str, object]:
        days_requested = None
        if self.draft.start_date and self.draft.end_date:
            days_requested = (self.draft.end_date - self.draft.start_date).days + 1

        return {
            "employee_id": self.draft.employee_id,
            "start_date": self.draft.start_date.isoformat() if self.draft.start_date else None,
            "end_date": self.draft.end_date.isoformat() if self.draft.end_date else None,
            "days_requested": days_requested,
            "reason_summary": self.draft.reason_summary,
            "handover_contact": self.draft.handover_contact,
            "handover_plan": self.draft.handover_plan,
            "urgency_level": self.draft.urgency_level.value if self.draft.urgency_level else None,
            "urgent_project_deadline": self.draft.urgent_project_deadline,
            "privacy_flagged": self.draft.privacy_flagged,
            "balance_status": asdict(self.draft.balance_status) if self.draft.balance_status else None,
            "approval_status": "pending_hr_review",
            "transcript": self.draft.chat_transcript,
            "submission_timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

    def _update_from_message(self, message: str) -> None:
        start_date, end_date = parse_date_range(message, today=self.today)
        if start_date and self.draft.start_date is None:
            self.draft.start_date = start_date
        if end_date and self.draft.end_date is None:
            self.draft.end_date = end_date

        reason = extract_reason(message, today=self.today)
        if reason and self.draft.reason_summary is None and any(
            marker in message.lower()
            for marker in {
                "because",
                "for",
                "vacation",
                "medical",
                "wedding",
                "family",
                "reason",
                "emergency",
                "personal",
                "appointment",
                "bereavement",
            }
        ):
            alert = privacy_filter(reason)
            self.draft.reason_summary = alert.safe_reason_summary
            self.draft.privacy_flagged = alert.contains_sensitive_medical_detail

        if reason and self.draft.reason_summary is None and self.draft.start_date and self.draft.end_date:
            alert = privacy_filter(reason)
            self.draft.reason_summary = alert.safe_reason_summary
            self.draft.privacy_flagged = alert.contains_sensitive_medical_detail

        contact, handover_plan = extract_handover(message)
        if contact and self.draft.handover_contact is None:
            self.draft.handover_contact = contact
        if handover_plan and self.draft.handover_plan is None:
            self.draft.handover_plan = handover_plan

        urgency_level, urgent_deadline = extract_urgency(message)
        if urgency_level and self.draft.urgency_level is None:
            self.draft.urgency_level = urgency_level
        if urgent_deadline is not None and self.draft.urgent_project_deadline is None:
            self.draft.urgent_project_deadline = urgent_deadline

        if self.draft.reason_summary is None and self.draft.start_date and len(message.split()) <= 5:
            # A short first message such as "I need tomorrow off" should trigger the next slot.
            return

    def _validate_dates(self) -> None:
        if self.draft.start_date and self.draft.end_date and self.draft.end_date < self.draft.start_date:
            self.draft.start_date, self.draft.end_date = self.draft.end_date, self.draft.start_date

    def _run_balance_check_if_ready(self) -> None:
        if (
            self.balance_checker is None
            or self.draft.balance_checked
            or self.draft.start_date is None
            or self.draft.end_date is None
        ):
            return

        self.draft.balance_status = self.balance_checker(self.draft)
        self.draft.balance_checked = True

    def _next_prompt(self) -> str:
        if self.draft.start_date is None:
            return "Please share the leave start date and end date so I can open the request."

        if self.draft.end_date is None:
            return f"I have the start date as {humanize_date(self.draft.start_date)}. What is the end date?"

        if self.draft.balance_status and not self.draft.balance_status.has_balance:
            remaining_days = (
                int(self.draft.balance_status.remaining_days)
                if self.draft.balance_status.remaining_days is not None
                else 0
            )
            plural = "day" if remaining_days == 1 else "days"
            return (
                f"I've noted your request, but please be aware you only have {remaining_days} {plural} of leave remaining. "
                "I can still prepare the request for HR review if you share the reason, handover contact, and urgency."
            )

        if self.draft.reason_summary is None:
            return (
                f"I can help with leave from {humanize_date(self.draft.start_date)} to "
                f"{humanize_date(self.draft.end_date)}. What is the reason for the leave? "
                "If it involves sensitive medical details, please keep the chat summary high level."
            )

        if self.draft.handover_contact is None:
            return "Who will cover your work while you are away, and is there any handover note HR should see?"

        if self.draft.urgency_level is None:
            return "How urgent is this request: low, medium, or high? Please mention any project deadlines."

        return "I have the information needed and am packaging it for HR approval."


def example_balance_checker(draft: LeaveRequestDraft) -> LeaveBalanceResult:
    if draft.start_date is None or draft.end_date is None:
        return LeaveBalanceResult(has_balance=False, note="Dates are required before balance can be checked.")

    days_requested = (draft.end_date - draft.start_date).days + 1
    remaining_days = 8.0 - days_requested
    return LeaveBalanceResult(
        has_balance=remaining_days >= 0,
        remaining_days=max(remaining_days, 0.0),
        note="Demo validator using a fixed eight-day balance.",
    )


if __name__ == "__main__":
    engine = LeaveInterviewEngine(
        today=date(2026, 4, 2),
        balance_checker=example_balance_checker,
    )
    print(engine.handle_message("I need next Tuesday off.", employee_id="EMP-1024"))
    print(engine.handle_message("It's for a family wedding. Sarah is covering. No deadlines."))
