from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"
    CANDIDATE = "CANDIDATE"


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


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
    department: str
    annual_allowance: float = Field(default=18)
    leave_balance: float = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Candidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    role_title: str
    resume_text: str = Field(sa_column=Column(Text, nullable=False))
    job_description: str = Field(default="", sa_column=Column(Text, nullable=False))
    ai_score: int = Field(default=0)
    resume_score: int = Field(default=0)
    interview_score: int = Field(default=0)
    skim_insights: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    screening_transcript: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    screening_questions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    raw_answers: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    interview_status: InterviewStatus = Field(default=InterviewStatus.PENDING)
    current_question_index: int = Field(default=0)
    summary: str = Field(default="")
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: CandidateStatus = Field(default=CandidateStatus.UNDER_REVIEW)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LeaveRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    start_date: date
    end_date: date
    reason: str
    status: LeaveStatus = Field(default=LeaveStatus.PENDING)
    handover_contact: str = Field(default="")
    handover_notes: str = Field(default="")
    urgency_level: str = Field(default="medium")
    privacy_flagged: bool = Field(default=False)
    transcript: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
