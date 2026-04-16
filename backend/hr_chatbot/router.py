from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class Workflow(str, Enum):
    RECRUITMENT_SCREENING = "recruitment_screening"
    LEAVE_MANAGEMENT = "leave_management"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RoutingDecision:
    workflow: Workflow
    confidence: float
    rationale: str


LEAVE_KEYWORDS = {
    "leave",
    "vacation",
    "pto",
    "time off",
    "take off",
    "annual leave",
    "sick leave",
    "day off",
    "handover",
    "covering",
}

RECRUITMENT_KEYWORDS = {
    "candidate",
    "interview",
    "resume",
    "cv",
    "job description",
    "screening",
    "application",
    "hiring manager",
    "role",
    "position",
}

DATE_SIGNAL_PATTERN = re.compile(
    r"\b("
    r"today|tomorrow|next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}"
    r")\b"
)


def _has_date_signal(message: str) -> bool:
    return DATE_SIGNAL_PATTERN.search(message) is not None


def classify_workflow(message: str) -> RoutingDecision:
    """Classify the first user turn into the correct HR workflow."""
    normalized = message.strip().lower()
    if not normalized:
        return RoutingDecision(Workflow.UNKNOWN, 0.0, "Empty message.")

    leave_hits = sum(keyword in normalized for keyword in LEAVE_KEYWORDS)
    recruitment_hits = sum(keyword in normalized for keyword in RECRUITMENT_KEYWORDS)
    has_date_signal = _has_date_signal(normalized)
    mentions_leave = any(keyword in normalized for keyword in {"leave", "time off", "day off", "take off", "pto"})
    mentions_recruitment = any(
        keyword in normalized
        for keyword in {"candidate", "resume", "cv", "interview", "job description", "hiring manager"}
    )

    if mentions_leave and has_date_signal:
        return RoutingDecision(
            workflow=Workflow.LEAVE_MANAGEMENT,
            confidence=0.9,
            rationale="Detected leave request phrasing with a date signal.",
        )

    if "apply" in normalized and mentions_leave:
        return RoutingDecision(
            workflow=Workflow.LEAVE_MANAGEMENT,
            confidence=0.82,
            rationale="Detected leave phrasing; treated 'apply' as leave-related in context.",
        )

    if mentions_recruitment and "apply" in normalized:
        return RoutingDecision(
            workflow=Workflow.RECRUITMENT_SCREENING,
            confidence=0.86,
            rationale="Detected recruitment context around an application request.",
        )

    if leave_hits > recruitment_hits and leave_hits > 0:
        return RoutingDecision(
            workflow=Workflow.LEAVE_MANAGEMENT,
            confidence=min(0.55 + (leave_hits * 0.1), 0.95),
            rationale="Detected leave-management vocabulary.",
        )

    if recruitment_hits > leave_hits and recruitment_hits > 0:
        return RoutingDecision(
            workflow=Workflow.RECRUITMENT_SCREENING,
            confidence=min(0.55 + (recruitment_hits * 0.1), 0.95),
            rationale="Detected recruitment-screening vocabulary.",
        )

    return RoutingDecision(
        workflow=Workflow.UNKNOWN,
        confidence=0.3,
        rationale="Not enough workflow-specific signals.",
    )
