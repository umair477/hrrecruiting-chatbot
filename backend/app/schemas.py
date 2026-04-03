from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import CandidateStatus, InterviewStatus, LeaveStatus, UserRole


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    user_id: int
    full_name: str


class UserProfile(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    employee_id: Optional[int] = None
    candidate_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class EmployeeRead(BaseModel):
    id: int
    name: str
    department: str
    annual_allowance: float
    leave_balance: float

    model_config = ConfigDict(from_attributes=True)


class CandidateRead(BaseModel):
    id: int
    name: str
    email: str
    role_title: str
    ai_score: int
    resume_score: int
    interview_score: int
    skim_insights: list[str]
    status: CandidateStatus
    interview_status: InterviewStatus
    summary: str
    skills: list[str]
    screening_transcript: list[str]
    screening_questions: list[str]
    raw_answers: list[dict[str, Any]]
    current_question_index: int
    job_description: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateScoreResponse(BaseModel):
    candidate: CandidateRead
    scorecard: dict[str, Any]
    resume_excerpt: str


class CandidateApplicationRequest(BaseModel):
    role_title: str
    job_description: str


class CandidateApplicationStatusResponse(BaseModel):
    candidate: Optional[CandidateRead] = None


class InterviewAnswerRequest(BaseModel):
    answer: str = Field(min_length=1)


class InterviewAnswerEvaluation(BaseModel):
    question: str
    answer: str
    score: int
    justification: str
    source: str


class CandidateInterviewResponse(BaseModel):
    candidate: CandidateRead
    evaluation: InterviewAnswerEvaluation
    next_question: Optional[str] = None


class LeaveRequestRead(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    department: str
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus
    handover_contact: str
    handover_notes: str
    urgency_level: str
    privacy_flagged: bool
    created_at: datetime


class LeaveRequestStatusUpdate(BaseModel):
    status: LeaveStatus


class LeaveBalanceRead(BaseModel):
    employee_id: int
    total: float
    used: float
    remaining: float
    provider: str


class AdminUserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    employee_id: Optional[int] = None
    candidate_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PromoteCandidateRequest(BaseModel):
    department: str = "Operations"
    annual_allowance: float = 18


class MetricCard(BaseModel):
    label: str
    value: str
    change: str


class AnalyticsPoint(BaseModel):
    label: str
    value: int


class AnalyticsOverview(BaseModel):
    stats: list[MetricCard]
    monthly_hires: list[AnalyticsPoint]
    candidates_by_department: list[AnalyticsPoint]


class MessagingPlatformStatus(BaseModel):
    name: str
    enabled: bool
    missing_configuration: list[str]
    notes: str


class HRISSyncResponse(BaseModel):
    provider: str
    employee_id: int
    leave_balance: float
    synced_at: datetime
    note: str


class ChatSocketInbound(BaseModel):
    message: str = Field(min_length=1)


class ChatSocketOutbound(BaseModel):
    thread_id: Optional[str] = None
    workflow: str
    reply: str
    missing_slots: list[str]
    privacy_note: Optional[str] = None
    structured_report: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
