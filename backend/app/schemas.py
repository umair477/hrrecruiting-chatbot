from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import (
    CandidateStatus,
    EmployeeRole,
    EmploymentType,
    InterviewStatus,
    JobStatus,
    LeaveStatus,
    LeaveType,
    UserRole,
)


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


class UnifiedLoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    role: Literal["admin", "employee", "candidate"]
    full_name: str
    employee_id: Optional[int] = None


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
    full_name: str = ""
    official_email: str = ""
    department: str
    designation: str = ""
    date_of_joining: date
    is_active: bool = True
    annual_allowance: float
    leave_balance: float

    model_config = ConfigDict(from_attributes=True)


class EmployeeSignupRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: str
    password: str
    confirm_password: str


class EmployeeLoginRequest(BaseModel):
    email: str
    password: str


class EmployeeSignupResponse(BaseModel):
    message: str


class EmployeeAuthProfile(BaseModel):
    employee_id: int
    full_name: str
    email: str
    department: str
    designation: str
    date_of_joining: date
    role: str = "EMPLOYEE"
    is_active: bool


class EmployeeAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee: EmployeeAuthProfile


class EmployeeLogoutResponse(BaseModel):
    message: str


class LeaveChatHistoryItem(BaseModel):
    role: str
    content: str


class LeaveChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_history: list[LeaveChatHistoryItem] = Field(default_factory=list)


class LeaveChatResponse(BaseModel):
    reply: str
    conversation_history: list[LeaveChatHistoryItem]


class EmployeeLeaveCreateRequest(BaseModel):
    leave_type: LeaveType
    start_date: date
    end_date: date
    total_days: Optional[int] = None
    reason: str = Field(min_length=3, max_length=1000)


class EmployeeLeaveRead(BaseModel):
    leave_id: int
    leave_type: LeaveType
    start_date: date
    end_date: date
    total_days: int
    reason: str
    status: LeaveStatus
    hr_note: str
    submitted_at: datetime


class EmployeeLeaveQuotaRead(BaseModel):
    annual_total: int
    annual_remaining: int
    sick_total: int
    sick_remaining: int
    casual_total: int
    casual_remaining: int
    unpaid_used: int


class CandidateRead(BaseModel):
    id: int
    first_name: str = ""
    last_name: str = ""
    name: str
    email: str
    job_id: Optional[int] = None
    role_title: str
    cv_summary: str = ""
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
    job_id: Optional[int] = None
    role_title: Optional[str] = None
    job_description: Optional[str] = None


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
    leave_type: LeaveType
    start_date: date
    end_date: date
    total_days: int
    reason: str
    status: LeaveStatus
    hr_note: str
    handover_contact: str
    handover_notes: str
    urgency_level: str
    privacy_flagged: bool
    submitted_at: datetime
    created_at: datetime


class LeaveRequestStatusUpdate(BaseModel):
    status: LeaveStatus
    hr_note: str = ""


class AdminEmployeeCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    official_email: str
    department: str = Field(min_length=2, max_length=120)
    designation: str = Field(min_length=2, max_length=120)
    date_of_joining: date
    role: EmployeeRole = EmployeeRole.EMPLOYEE


class AdminEmployeeUpdateRequest(BaseModel):
    department: Optional[str] = Field(default=None, min_length=2, max_length=120)
    designation: Optional[str] = Field(default=None, min_length=2, max_length=120)
    role: Optional[EmployeeRole] = None
    is_active: Optional[bool] = None


class AdminEmployeeRead(BaseModel):
    employee_id: int
    full_name: str
    official_email: str
    department: str
    designation: str
    date_of_joining: date
    role: EmployeeRole
    is_active: bool
    password_set: bool
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int
    casual_total: int
    casual_used: int
    casual_remaining: int
    unpaid_used: int


class AdminEmployeeCreateResponse(BaseModel):
    message: str
    employee_id: int


class AdminJobCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=200)


class AdminJobUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = None
    required_skills: Optional[list[str]] = None
    experience_years: Optional[int] = Field(default=None, ge=0, le=40)
    employment_type: Optional[EmploymentType] = None
    salary_range: Optional[str] = None
    responsibilities: Optional[list[str]] = None
    nice_to_have_qualifications: Optional[list[str]] = None
    status: Optional[JobStatus] = None


class JobRead(BaseModel):
    job_id: int
    title: str
    description: str
    required_skills: list[str]
    experience_years: int
    employment_type: EmploymentType
    salary_range: Optional[str] = None
    responsibilities: list[str]
    nice_to_have_qualifications: list[str]
    status: JobStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicJobRead(BaseModel):
    job_id: int
    title: str
    description: str
    required_skills: list[str]
    experience_years: int
    employment_type: EmploymentType
    salary_range: Optional[str] = None
    responsibilities: list[str]
    nice_to_have_qualifications: list[str]
    status: JobStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicJobListingRead(BaseModel):
    job_id: int
    title: str
    employment_type: EmploymentType
    experience_years: int
    description: str
    responsibilities: list[str]

    model_config = ConfigDict(from_attributes=True)


class CandidatePublicApplyRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str


class CandidateCVUploadResponse(BaseModel):
    candidate_id: int
    full_name: str
    email: str
    total_years_experience: float
    top_skills: list[str]
    extracted_summary: dict[str, Any]
    reply: str


class CandidatePublicApplyResponse(BaseModel):
    session_id: str
    candidate_id: int
    reply: str
    question_number: int
    total_questions: int = 6


class CandidatePublicChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class CandidatePublicChatResponse(BaseModel):
    reply: str
    question_number: int
    total_questions: int
    requires_elaboration: bool = False
    ready_for_submission: bool = False


class CandidatePublicSubmitRequest(BaseModel):
    session_id: str


class CandidatePublicSubmitResponse(BaseModel):
    reply: str
    submitted: bool = True


class CandidateScoreBreakdown(BaseModel):
    question: str
    answer: str
    score: int
    justification: str
    source: str


class AdminCandidateRead(BaseModel):
    candidate_id: int
    first_name: str
    last_name: str
    email: str
    job_id: Optional[int] = None
    job_position: str
    cv_summary: str
    screening_score: int
    recommendation_label: str
    interview_email_sent: bool
    interview_date: Optional[date] = None
    interview_email_sent_at: Optional[datetime] = None
    interview_transcript: list[dict[str, Any]]
    score_breakdown: list[CandidateScoreBreakdown]
    applied_at: datetime


class InterviewEmailGenerateRequest(BaseModel):
    interview_date: date
    interview_time: str
    interview_format: str
    location_or_link: str
    additional_notes: str = ""


class InterviewEmailDraftResponse(BaseModel):
    to_email: str
    subject: str
    body: str


class InterviewEmailSendRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    interview_date: Optional[date] = None


class AdminLeaveRead(BaseModel):
    leave_id: int
    employee_id: int
    employee_name: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    total_days: int
    reason: str
    status: LeaveStatus
    hr_note: str
    email_sent_at: Optional[datetime] = None
    submitted_at: datetime


class LeaveQuotaRead(BaseModel):
    employee_id: int
    employee_name: str
    year: int
    annual_total: int
    annual_used: int
    annual_remaining: int
    sick_total: int
    sick_used: int
    sick_remaining: int
    casual_total: int
    casual_used: int
    casual_remaining: int
    unpaid_used: int


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
    annual_allowance: float = 20


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
