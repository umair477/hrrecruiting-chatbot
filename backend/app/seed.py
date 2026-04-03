from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from backend.app.core.security import hash_password
from backend.app.models import Candidate, CandidateStatus, Employee, InterviewStatus, LeaveRequest, LeaveStatus, User, UserRole


def seed_database(session: Session) -> None:
    if session.exec(select(User)).first() is not None:
        return

    employees = [
        Employee(name="Sarah Mitchell", department="Engineering", annual_allowance=18, leave_balance=12),
        Employee(name="Raj Patel", department="Design", annual_allowance=18, leave_balance=8),
        Employee(name="Tom Anderson", department="Marketing", annual_allowance=18, leave_balance=6),
    ]
    for employee in employees:
        session.add(employee)
    session.commit()
    for employee in employees:
        session.refresh(employee)

    candidates = [
        Candidate(
            name="Priya Sharma",
            email="priya@talentspark.dev",
            role_title="Senior Frontend Engineer",
            resume_text="React TypeScript performance design systems GraphQL leadership",
            job_description="Frontend engineer role focused on React, TypeScript, GraphQL, performance, and design systems.",
            ai_score=95,
            resume_score=90,
            interview_score=98,
            skim_insights=[
                "Strong overlap with the role in React, TypeScript, GraphQL, and design systems.",
                "CV suggests measurable delivery impact and leadership in frontend platform work.",
                "Interview should probe performance trade-offs and cross-team influence depth.",
            ],
            screening_transcript=[
                "Led a design system rollout across product teams.",
                "Improved page performance and stakeholder alignment.",
            ],
            screening_questions=[
                "Tell me about a time you used react to deliver a measurable outcome.",
                "Describe a challenging situation involving typescript and how you handled it.",
                "Give an example of how you communicated trade-offs while working on graphql.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            raw_answers=[
                {
                    "question": "Tell me about a time you used react to deliver a measurable outcome.",
                    "answer": "Led a design system rollout across product teams.",
                    "score": 10,
                    "justification": "Strong ownership and measurable frontend impact.",
                    "source": "seed",
                },
                {
                    "question": "Describe a challenging situation involving typescript and how you handled it.",
                    "answer": "Improved page performance and stakeholder alignment.",
                    "score": 10,
                    "justification": "Clear technical depth with strong communication.",
                    "source": "seed",
                },
            ],
            interview_status=InterviewStatus.IN_PROGRESS,
            current_question_index=2,
            summary="Excellent frontend profile with strong communication and measurable delivery impact.",
            skills=["react", "typescript", "graphql", "design"],
            status=CandidateStatus.SHORTLISTED,
        ),
        Candidate(
            name="James Carter",
            email="james@talentspark.dev",
            role_title="Product Designer",
            resume_text="Figma design systems user research SaaS prototyping",
            job_description="Product designer role covering Figma, design systems, research, prototyping, and stakeholder communication.",
            ai_score=88,
            resume_score=84,
            interview_score=90,
            skim_insights=[
                "Clear design systems and research alignment for a SaaS product environment.",
                "Candidate appears strong in presenting trade-offs to stakeholders.",
                "Interview should validate quantitative product impact and experimentation depth.",
            ],
            screening_transcript=[
                "Balanced user research with tight delivery timelines.",
                "Presented design trade-offs to product leadership.",
            ],
            screening_questions=[
                "Tell me about a time you used figma to deliver a measurable outcome.",
                "Describe a challenging situation involving design and how you handled it.",
                "Give an example of how you communicated trade-offs while working on research.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            raw_answers=[
                {
                    "question": "Tell me about a time you used figma to deliver a measurable outcome.",
                    "answer": "Balanced user research with tight delivery timelines.",
                    "score": 9,
                    "justification": "Good role alignment and concise delivery impact.",
                    "source": "seed",
                },
                {
                    "question": "Give an example of how you communicated trade-offs while working on research.",
                    "answer": "Presented design trade-offs to product leadership.",
                    "score": 9,
                    "justification": "Strong communication and stakeholder management.",
                    "source": "seed",
                },
            ],
            interview_status=InterviewStatus.IN_PROGRESS,
            current_question_index=2,
            summary="Strong design candidate with polished communication and SaaS experience.",
            skills=["figma", "design", "research"],
            status=CandidateStatus.INTERVIEW_SCHEDULED,
        ),
        Candidate(
            name="Aisha Patel",
            email="aisha@talentspark.dev",
            role_title="Data Analyst",
            resume_text="Python SQL Tableau analytics stakeholder reporting",
            job_description="Data analyst role focused on Python, SQL, Tableau, analytics, and stakeholder reporting.",
            ai_score=76,
            resume_score=74,
            interview_score=78,
            skim_insights=[
                "Relevant match on Python, SQL, Tableau, and stakeholder-facing analytics work.",
                "Profile suggests solid execution on reporting and dashboard troubleshooting.",
                "Interview should test executive communication and analytical prioritization.",
            ],
            screening_transcript=[
                "Resolved reporting issues through SQL optimization.",
                "Explained trends to non-technical partners.",
            ],
            screening_questions=[
                "Tell me about a time you used python to deliver a measurable outcome.",
                "Describe a challenging situation involving sql and how you handled it.",
                "Give an example of how you communicated trade-offs while working on tableau.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            raw_answers=[
                {
                    "question": "Describe a challenging situation involving sql and how you handled it.",
                    "answer": "Resolved reporting issues through SQL optimization.",
                    "score": 8,
                    "justification": "Solid analytical response with a concrete outcome.",
                    "source": "seed",
                },
                {
                    "question": "Give an example of how you communicated trade-offs while working on tableau.",
                    "answer": "Explained trends to non-technical partners.",
                    "score": 8,
                    "justification": "Good communication with limited strategic detail.",
                    "source": "seed",
                },
            ],
            interview_status=InterviewStatus.IN_PROGRESS,
            current_question_index=2,
            summary="Solid analytical baseline with room to improve executive communication.",
            skills=["python", "sql", "tableau"],
            status=CandidateStatus.UNDER_REVIEW,
        ),
    ]
    for candidate in candidates:
        session.add(candidate)
    session.commit()

    users = [
        User(
            email="admin.hr@talentspark.dev",
            full_name="Helen HR",
            hashed_password=hash_password("admin123"),
            role=UserRole.ADMIN,
            employee_id=employees[0].id,
        ),
        User(
            email="employee@talentspark.dev",
            full_name="Raj Patel",
            hashed_password=hash_password("user123"),
            role=UserRole.EMPLOYEE,
            employee_id=employees[1].id,
        ),
        User(
            email="candidate@talentspark.dev",
            full_name="Aisha Patel",
            hashed_password=hash_password("user123"),
            role=UserRole.CANDIDATE,
            candidate_id=candidates[2].id,
        ),
    ]
    for user in users:
        session.add(user)

    session.add(
        LeaveRequest(
            employee_id=employees[0].id,
            start_date=date(2026, 4, 7),
            end_date=date(2026, 4, 11),
            reason="Family vacation planned months ago.",
            status=LeaveStatus.PENDING,
            handover_contact="Daniel",
            handover_notes="Coverage shared with Daniel.",
            urgency_level="low",
            privacy_flagged=False,
            transcript=[],
        )
    )
    session.add(
        LeaveRequest(
            employee_id=employees[1].id,
            start_date=date(2026, 4, 14),
            end_date=date(2026, 4, 15),
            reason="Medical leave requested. Detailed diagnosis omitted from chat log.",
            status=LeaveStatus.PENDING,
            handover_contact="Priya",
            handover_notes="Priya will monitor urgent design tickets.",
            urgency_level="medium",
            privacy_flagged=True,
            transcript=[],
        )
    )
    session.commit()
