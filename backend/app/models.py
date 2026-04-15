from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, Enum as SQLEnum, JSON, Text
from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"
    CANDIDATE = "CANDIDATE"
    USER = "USER"


class EmployeeRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DENIED = "rejected"


class LeaveType(str, Enum):
    ANNUAL = "Annual"
    SICK = "Sick"
    CASUAL = "Casual"
    UNPAID = "Unpaid"


class JobStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class EmploymentType(str, Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT = "Contract"


class CandidateStatus(str, Enum):
    SHORTLISTED = "Shortlisted"
    UNDER_REVIEW = "Under Review"
    REJECTED = "Rejected"
    INTERVIEW_SCHEDULED = "Interview Scheduled"


class InterviewStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    full_name: str
    hashed_password: str
    role: UserRole = Field(default=UserRole.CANDIDATE)
    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    candidate_id: Optional[int] = Field(default=None, foreign_key="candidate.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Employee(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    full_name: str = Field(default="")
    official_email: str = Field(default="", index=True)
    department: str
    designation: str = Field(default="")
    date_of_joining: date = Field(default_factory=date.today)
    password_hash: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    role: EmployeeRole = Field(
        default=EmployeeRole.EMPLOYEE,
        sa_column=Column(
            SQLEnum(
                EmployeeRole,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=EmployeeRole.EMPLOYEE.value,
        ),
    )
    failed_login_attempts: int = Field(default=0)
    locked_until: Optional[datetime] = Field(default=None)
    last_login_at: Optional[datetime] = Field(default=None)
    annual_allowance: float = Field(default=20)
    leave_balance: float = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    job_id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    required_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    experience_years: int = Field(default=0)
    employment_type: EmploymentType = Field(
        default=EmploymentType.FULL_TIME,
        sa_column=Column(
            SQLEnum(
                EmploymentType,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=EmploymentType.FULL_TIME.value,
        ),
    )
    salary_range: Optional[str] = Field(default=None)
    responsibilities: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    nice_to_have_qualifications: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: JobStatus = Field(
        default=JobStatus.OPEN,
        sa_column=Column(
            SQLEnum(
                JobStatus,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=JobStatus.OPEN.value,
        ),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Candidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    first_name: str = Field(default="")
    last_name: str = Field(default="")
    name: str
    email: str = Field(index=True, unique=True)
    job_id: Optional[int] = Field(default=None, foreign_key="jobs.job_id", index=True)
    role_title: str
    resume_text: str = Field(sa_column=Column(Text, nullable=False))
    cv_extracted_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    job_description: str = Field(default="", sa_column=Column(Text, nullable=False))
    cv_summary: str = Field(default="", sa_column=Column(Text, nullable=False))
    ai_score: int = Field(default=0)
    screening_score: float = Field(default=0)
    resume_score: int = Field(default=0)
    interview_score: int = Field(default=0)
    recommendation_label: str = Field(default="")
    skim_insights: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    screening_transcript: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    interview_transcript: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    screening_questions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    raw_answers: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    interview_status: InterviewStatus = Field(
        default=InterviewStatus.PENDING,
        sa_column=Column(
            SQLEnum(
                InterviewStatus,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=InterviewStatus.PENDING.value,
        ),
    )
    current_question_index: int = Field(default=0)
    summary: str = Field(default="")
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: CandidateStatus = Field(
        default=CandidateStatus.UNDER_REVIEW,
        sa_column=Column(
            SQLEnum(
                CandidateStatus,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=CandidateStatus.UNDER_REVIEW.value,
        ),
    )
    interview_email_sent: bool = Field(default=False)
    interview_date: Optional[date] = Field(default=None)
    interview_email_sent_at: Optional[datetime] = Field(default=None)
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LeaveRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    leave_type: LeaveType = Field(
        default=LeaveType.ANNUAL,
        sa_column=Column(
            SQLEnum(
                LeaveType,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=LeaveType.ANNUAL.value,
        ),
    )
    start_date: date
    end_date: date
    total_days: int = Field(default=1)
    reason: str
    status: LeaveStatus = Field(
        default=LeaveStatus.PENDING,
        sa_column=Column(
            SQLEnum(
                LeaveStatus,
                values_callable=lambda enum_cls: [member.value for member in enum_cls],
                native_enum=False,
                validate_strings=True,
            ),
            nullable=False,
            default=LeaveStatus.PENDING.value,
        ),
    )
    hr_note: str = Field(default="")
    handover_contact: str = Field(default="")
    handover_notes: str = Field(default="")
    urgency_level: str = Field(default="medium")
    privacy_flagged: bool = Field(default=False)
    transcript: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LeaveQuota(SQLModel, table=True):
    __tablename__ = "leave_quota"

    quota_id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    year: int = Field(index=True)
    annual_total: int = Field(default=20)
    annual_used: int = Field(default=0)
    sick_total: int = Field(default=10)
    sick_used: int = Field(default=0)
    casual_total: int = Field(default=5)
    casual_used: int = Field(default=0)
    unpaid_used: int = Field(default=0)


class TokenBlocklist(SQLModel, table=True):
    __tablename__ = "token_blocklist"

    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    notification_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    notification_type: str = Field(default="")
    subject: str = Field(default="")
    body: str = Field(default="")
    sent_to_email: str = Field(default="")
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="sent")


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor_type: str = Field(default="system", index=True)
    actor_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)
    entity_type: str = Field(index=True)
    entity_id: str = Field(index=True)
    details: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CandidateAsyncJob(SQLModel, table=True):
    __tablename__ = "candidate_async_jobs"

    job_id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    job_type: str = Field(default="candidate_cv_upload", index=True)
    status: str = Field(default="queued", index=True)
    candidate_id: Optional[int] = Field(default=None, foreign_key="candidate.id", index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error_message: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IdempotencyRecord(SQLModel, table=True):
    __tablename__ = "idempotency_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    idempotency_key: str = Field(index=True, unique=True)
    endpoint: str = Field(index=True)
    request_hash: str = Field(index=True)
    response_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CandidatePortalToken(SQLModel, table=True):
    __tablename__ = "candidate_portal_tokens"

    token: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
