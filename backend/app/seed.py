from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Session, select

from backend.app.core.security import hash_password
from backend.app.models import (
    Candidate,
    CandidateStatus,
    Employee,
    EmployeeRole,
    EmploymentType,
    InterviewStatus,
    Job,
    JobStatus,
    LeaveQuota,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    User,
    UserRole,
)
from backend.app.services.admin_dashboard import split_full_name
from backend.app.services.leave import calculate_leave_days


def seed_database(session: Session) -> None:
    employees = _ensure_employees(session)
    _ensure_admin_employee(session, employees)
    jobs = _ensure_jobs(session)
    candidates = _ensure_candidates(session, jobs)
    _ensure_users(session, employees, candidates)
    _ensure_leave_requests(session, employees)
    _ensure_leave_quotas(session, employees)
    session.commit()


def _ensure_employees(session: Session) -> dict[str, Employee]:
    seed_employees = [
        {
            "name": "Sarah Mitchell",
            "official_email": "sarah.mitchell@talentspark.dev",
            "department": "Engineering",
            "designation": "Engineering Manager",
            "date_of_joining": date(2024, 2, 12),
            "role": EmployeeRole.EMPLOYEE,
        },
        {
            "name": "Raj Patel",
            "official_email": "raj.patel@talentspark.dev",
            "department": "Design",
            "designation": "Product Designer",
            "date_of_joining": date(2024, 6, 3),
            "role": EmployeeRole.EMPLOYEE,
        },
        {
            "name": "Tom Anderson",
            "official_email": "tom.anderson@talentspark.dev",
            "department": "Marketing",
            "designation": "Marketing Specialist",
            "date_of_joining": date(2023, 11, 20),
            "role": EmployeeRole.EMPLOYEE,
        },
        {
            "name": "Maya Thompson",
            "official_email": "maya.thompson@talentspark.dev",
            "department": "Engineering",
            "designation": "Engineering Manager",
            "date_of_joining": date(2022, 9, 14),
            "role": EmployeeRole.MANAGER,
        },
    ]
    employees_by_name: dict[str, Employee] = {}
    for payload in seed_employees:
        employee = session.exec(select(Employee).where(Employee.name == payload["name"])).first()
        if employee is None:
            employee = Employee(
                name=payload["name"],
                full_name=payload["name"],
                official_email=payload["official_email"],
                department=payload["department"],
                designation=payload["designation"],
                date_of_joining=payload["date_of_joining"],
                password_hash=None,
                is_active=True,
                role=payload["role"],
                annual_allowance=20,
                leave_balance=20,
            )
        else:
            employee.name = payload["name"]
            employee.full_name = payload["name"]
            if not employee.official_email:
                employee.official_email = payload["official_email"]
            employee.department = payload["department"]
            if not employee.designation:
                employee.designation = payload["designation"]
            if employee.date_of_joining is None:
                employee.date_of_joining = payload["date_of_joining"]
            employee.is_active = True
            if employee.role not in {EmployeeRole.ADMIN, EmployeeRole.MANAGER, EmployeeRole.EMPLOYEE}:
                employee.role = payload["role"]
            if employee.annual_allowance <= 0:
                employee.annual_allowance = 20
            if employee.leave_balance <= 0:
                employee.leave_balance = 20
        session.add(employee)
        session.commit()
        session.refresh(employee)
        employees_by_name[payload["name"]] = employee
    return employees_by_name


def _ensure_admin_employee(session: Session, employees: dict[str, Employee]) -> None:
    admin_employee = session.exec(
        select(Employee).where(Employee.official_email == "admin@company.com")
    ).first()
    existing_admin = session.exec(select(Employee).where(Employee.role == EmployeeRole.ADMIN)).first()

    if existing_admin is None and admin_employee is None:
        admin_employee = Employee(
            name="HR Admin",
            full_name="HR Admin",
            official_email="admin@company.com",
            department="Human Resources",
            designation="HR Manager",
            date_of_joining=date(2024, 1, 1),
            password_hash=hash_password("Admin@1234"),
            is_active=True,
            role=EmployeeRole.ADMIN,
            annual_allowance=20,
            leave_balance=20,
        )
    elif admin_employee is None and existing_admin is not None:
        admin_employee = existing_admin

    if admin_employee is None:
        return

    admin_employee.role = EmployeeRole.ADMIN
    admin_employee.is_active = True
    if not admin_employee.password_hash:
        admin_employee.password_hash = hash_password("Admin@1234")

    session.add(admin_employee)
    session.commit()
    session.refresh(admin_employee)
    employees[admin_employee.full_name or admin_employee.name] = admin_employee


def _ensure_jobs(session: Session) -> dict[str, Job]:
    seed_jobs = [
        {
            "title": "Senior Frontend Engineer",
            "description": "Lead React and TypeScript delivery across customer-facing products, design systems, and performance-sensitive flows.",
            "required_skills": ["React", "TypeScript", "GraphQL", "Design Systems", "Performance Optimization"],
            "experience_years": 5,
            "employment_type": EmploymentType.FULL_TIME,
            "salary_range": "$120,000 - $155,000",
            "responsibilities": [
                "Lead complex frontend feature delivery from discovery through production.",
                "Improve design system consistency, accessibility, and responsiveness.",
                "Partner with product and design on execution trade-offs and roadmap planning.",
                "Coach engineers on code quality, performance, and maintainable UI patterns.",
            ],
            "nice_to_have_qualifications": [
                "Experience scaling design systems across multiple teams",
                "GraphQL and performance tooling background",
                "Mentorship experience in frontend platform work",
            ],
        },
        {
            "title": "Product Designer",
            "description": "Own research-informed product design for SaaS workflows, from problem framing to polished execution and stakeholder alignment.",
            "required_skills": ["Figma", "User Research", "Prototyping", "Design Systems", "Stakeholder Communication"],
            "experience_years": 4,
            "employment_type": EmploymentType.FULL_TIME,
            "salary_range": "$95,000 - $125,000",
            "responsibilities": [
                "Translate product opportunities into user-centered interface concepts.",
                "Run research, prototype flows, and validate decisions with stakeholders.",
                "Collaborate closely with engineers on implementation details and constraints.",
                "Maintain consistency across the product experience and design system.",
            ],
            "nice_to_have_qualifications": [
                "SaaS product design experience",
                "Metrics-informed experimentation background",
                "Comfort presenting design rationale to leadership",
            ],
        },
        {
            "title": "Data Analyst",
            "description": "Deliver high-trust analytics, dashboards, and reporting that help teams make faster and better operational decisions.",
            "required_skills": ["Python", "SQL", "Tableau", "Reporting", "Stakeholder Communication"],
            "experience_years": 3,
            "employment_type": EmploymentType.FULL_TIME,
            "salary_range": "$85,000 - $115,000",
            "responsibilities": [
                "Build and maintain dashboards for hiring and business operations.",
                "Translate ambiguous questions into reliable analyses and recommendations.",
                "Improve reporting accuracy, speed, and stakeholder visibility.",
                "Partner with cross-functional teams to prioritize analytics work.",
            ],
            "nice_to_have_qualifications": [
                "Recruiting or HR analytics exposure",
                "Experience with data quality investigations",
                "Strong storytelling with data",
            ],
        },
    ]

    jobs_by_title: dict[str, Job] = {}
    for payload in seed_jobs:
        job = session.exec(select(Job).where(Job.title == payload["title"])).first()
        if job is None:
            job = Job(**payload, status=JobStatus.OPEN)
        else:
            job.description = payload["description"]
            job.required_skills = payload["required_skills"]
            job.experience_years = payload["experience_years"]
            job.employment_type = payload["employment_type"]
            job.salary_range = payload["salary_range"]
            job.responsibilities = payload["responsibilities"]
            job.nice_to_have_qualifications = payload["nice_to_have_qualifications"]
            if job.status not in {JobStatus.OPEN, JobStatus.CLOSED}:
                job.status = JobStatus.OPEN
        session.add(job)
        session.commit()
        session.refresh(job)
        jobs_by_title[payload["title"]] = job
    return jobs_by_title


def _ensure_candidates(session: Session, jobs: dict[str, Job]) -> dict[str, Candidate]:
    seed_candidates = [
        {
            "name": "Priya Sharma",
            "email": "priya@talentspark.dev",
            "role_title": "Senior Frontend Engineer",
            "resume_text": "React TypeScript performance design systems GraphQL leadership",
            "job_description": jobs["Senior Frontend Engineer"].description,
            "cv_summary": "Excellent frontend profile with strong communication and measurable delivery impact.",
            "ai_score": 95,
            "resume_score": 90,
            "interview_score": 98,
            "skim_insights": [
                "Strong overlap with the role in React, TypeScript, GraphQL, and design systems.",
                "CV suggests measurable delivery impact and leadership in frontend platform work.",
                "Interview should probe performance trade-offs and cross-team influence depth.",
            ],
            "screening_transcript": [
                "Led a design system rollout across product teams.",
                "Improved page performance and stakeholder alignment.",
            ],
            "screening_questions": [
                "Tell me about a time you used React to deliver a measurable outcome.",
                "Describe a challenging situation involving TypeScript and how you handled it.",
                "Give an example of how you communicated trade-offs while working on GraphQL.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            "raw_answers": [
                {
                    "question": "Tell me about a time you used React to deliver a measurable outcome.",
                    "answer": "Led a design system rollout across product teams.",
                    "score": 10,
                    "justification": "Strong ownership and measurable frontend impact.",
                    "source": "seed",
                },
                {
                    "question": "Describe a challenging situation involving TypeScript and how you handled it.",
                    "answer": "Improved page performance and stakeholder alignment.",
                    "score": 10,
                    "justification": "Clear technical depth with strong communication.",
                    "source": "seed",
                },
            ],
            "interview_status": InterviewStatus.IN_PROGRESS,
            "current_question_index": 2,
            "summary": "Excellent frontend profile with strong communication and measurable delivery impact.",
            "skills": ["react", "typescript", "graphql", "design"],
            "status": CandidateStatus.SHORTLISTED,
        },
        {
            "name": "James Carter",
            "email": "james@talentspark.dev",
            "role_title": "Product Designer",
            "resume_text": "Figma design systems user research SaaS prototyping",
            "job_description": jobs["Product Designer"].description,
            "cv_summary": "Strong design candidate with polished communication and SaaS experience.",
            "ai_score": 88,
            "resume_score": 84,
            "interview_score": 90,
            "skim_insights": [
                "Clear design systems and research alignment for a SaaS product environment.",
                "Candidate appears strong in presenting trade-offs to stakeholders.",
                "Interview should validate quantitative product impact and experimentation depth.",
            ],
            "screening_transcript": [
                "Balanced user research with tight delivery timelines.",
                "Presented design trade-offs to product leadership.",
            ],
            "screening_questions": [
                "Tell me about a time you used Figma to deliver a measurable outcome.",
                "Describe a challenging situation involving design and how you handled it.",
                "Give an example of how you communicated trade-offs while working on research.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            "raw_answers": [
                {
                    "question": "Tell me about a time you used Figma to deliver a measurable outcome.",
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
            "interview_status": InterviewStatus.IN_PROGRESS,
            "current_question_index": 2,
            "summary": "Strong design candidate with polished communication and SaaS experience.",
            "skills": ["figma", "design", "research"],
            "status": CandidateStatus.INTERVIEW_SCHEDULED,
        },
        {
            "name": "Aisha Patel",
            "email": "aisha@talentspark.dev",
            "role_title": "Data Analyst",
            "resume_text": "Python SQL Tableau analytics stakeholder reporting",
            "job_description": jobs["Data Analyst"].description,
            "cv_summary": "Solid analytical baseline with room to improve executive communication.",
            "ai_score": 76,
            "resume_score": 74,
            "interview_score": 78,
            "skim_insights": [
                "Relevant match on Python, SQL, Tableau, and stakeholder-facing analytics work.",
                "Profile suggests solid execution on reporting and dashboard troubleshooting.",
                "Interview should test executive communication and analytical prioritization.",
            ],
            "screening_transcript": [
                "Resolved reporting issues through SQL optimization.",
                "Explained trends to non-technical partners.",
            ],
            "screening_questions": [
                "Tell me about a time you used Python to deliver a measurable outcome.",
                "Describe a challenging situation involving SQL and how you handled it.",
                "Give an example of how you communicated trade-offs while working on Tableau.",
                "Tell me about a time you had to learn something quickly to succeed in a role.",
            ],
            "raw_answers": [
                {
                    "question": "Describe a challenging situation involving SQL and how you handled it.",
                    "answer": "Resolved reporting issues through SQL optimization.",
                    "score": 8,
                    "justification": "Solid analytical response with a concrete outcome.",
                    "source": "seed",
                },
                {
                    "question": "Give an example of how you communicated trade-offs while working on Tableau.",
                    "answer": "Explained trends to non-technical partners.",
                    "score": 8,
                    "justification": "Good communication with limited strategic detail.",
                    "source": "seed",
                },
            ],
            "interview_status": InterviewStatus.IN_PROGRESS,
            "current_question_index": 2,
            "summary": "Solid analytical baseline with room to improve executive communication.",
            "skills": ["python", "sql", "tableau"],
            "status": CandidateStatus.UNDER_REVIEW,
        },
    ]

    candidates_by_email: dict[str, Candidate] = {}
    for payload in seed_candidates:
        job = jobs[payload["role_title"]]
        first_name, last_name = split_full_name(payload["name"])
        candidate = session.exec(select(Candidate).where(Candidate.email == payload["email"])).first()
        if candidate is None:
            candidate = Candidate(
                first_name=first_name,
                last_name=last_name,
                name=payload["name"],
                email=payload["email"],
                job_id=job.job_id,
                role_title=payload["role_title"],
                resume_text=payload["resume_text"],
                job_description=payload["job_description"],
                cv_summary=payload["cv_summary"],
                ai_score=payload["ai_score"],
                resume_score=payload["resume_score"],
                interview_score=payload["interview_score"],
                skim_insights=payload["skim_insights"],
                screening_transcript=payload["screening_transcript"],
                screening_questions=payload["screening_questions"],
                raw_answers=payload["raw_answers"],
                interview_status=payload["interview_status"],
                current_question_index=payload["current_question_index"],
                summary=payload["summary"],
                skills=payload["skills"],
                status=payload["status"],
            )
        else:
            candidate.first_name = first_name
            candidate.last_name = last_name
            candidate.name = payload["name"]
            candidate.job_id = job.job_id
            candidate.role_title = payload["role_title"]
            candidate.resume_text = payload["resume_text"]
            candidate.job_description = payload["job_description"]
            candidate.cv_summary = payload["cv_summary"]
            candidate.ai_score = payload["ai_score"]
            candidate.resume_score = payload["resume_score"]
            candidate.interview_score = payload["interview_score"]
            candidate.skim_insights = payload["skim_insights"]
            candidate.screening_transcript = payload["screening_transcript"]
            candidate.screening_questions = payload["screening_questions"]
            candidate.raw_answers = payload["raw_answers"]
            candidate.interview_status = payload["interview_status"]
            candidate.current_question_index = payload["current_question_index"]
            candidate.summary = payload["summary"]
            candidate.skills = payload["skills"]
            candidate.status = payload["status"]
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
        candidates_by_email[payload["email"]] = candidate
    return candidates_by_email


def _ensure_users(session: Session, employees: dict[str, Employee], candidates: dict[str, Candidate]) -> None:
    admin_employee = session.exec(select(Employee).where(Employee.official_email == "admin@company.com")).first()
    admin_employee_id = admin_employee.id if admin_employee is not None else employees["Sarah Mitchell"].id
    seed_users = [
        {
            "email": "admin.hr@talentspark.dev",
            "full_name": "Helen HR",
            "password": "admin123",
            "role": UserRole.ADMIN,
            "employee_id": admin_employee_id,
            "candidate_id": None,
        },
        {
            "email": "admin@company.com",
            "full_name": "HR Admin",
            "password": "Admin@1234",
            "role": UserRole.ADMIN,
            "employee_id": admin_employee_id,
            "candidate_id": None,
        },
        {
            "email": "candidate@talentspark.dev",
            "full_name": "Aisha Patel",
            "password": "user123",
            "role": UserRole.CANDIDATE,
            "employee_id": None,
            "candidate_id": candidates["aisha@talentspark.dev"].id,
        },
    ]

    for payload in seed_users:
        user = session.exec(select(User).where(User.email == payload["email"])).first()
        if user is None:
            user = User(
                email=payload["email"],
                full_name=payload["full_name"],
                hashed_password=hash_password(payload["password"]),
                role=payload["role"],
                employee_id=payload["employee_id"],
                candidate_id=payload["candidate_id"],
            )
        else:
            user.full_name = payload["full_name"]
            user.role = payload["role"]
            user.employee_id = payload["employee_id"]
            user.candidate_id = payload["candidate_id"]
            if not user.hashed_password:
                user.hashed_password = hash_password(payload["password"])
        session.add(user)
    session.commit()


def _ensure_leave_requests(session: Session, employees: dict[str, Employee]) -> None:
    seed_leaves = [
        {
            "employee_id": employees["Sarah Mitchell"].id,
            "leave_type": LeaveType.ANNUAL,
            "start_date": date(2026, 4, 7),
            "end_date": date(2026, 4, 11),
            "reason": "Family vacation planned months ago.",
            "status": LeaveStatus.PENDING,
            "hr_note": "",
            "handover_contact": "Daniel",
            "handover_notes": "Coverage shared with Daniel.",
            "urgency_level": "low",
            "privacy_flagged": False,
            "transcript": [],
            "submitted_at": datetime(2026, 4, 1, 9, 0, 0),
        },
        {
            "employee_id": employees["Raj Patel"].id,
            "leave_type": LeaveType.SICK,
            "start_date": date(2026, 4, 14),
            "end_date": date(2026, 4, 15),
            "reason": "Medical leave requested. Detailed diagnosis omitted from chat log.",
            "status": LeaveStatus.PENDING,
            "hr_note": "",
            "handover_contact": "Priya",
            "handover_notes": "Priya will monitor urgent design tickets.",
            "urgency_level": "medium",
            "privacy_flagged": True,
            "transcript": [],
            "submitted_at": datetime(2026, 4, 13, 11, 0, 0),
        },
    ]

    for payload in seed_leaves:
        leave_request = session.exec(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == payload["employee_id"],
                LeaveRequest.start_date == payload["start_date"],
                LeaveRequest.end_date == payload["end_date"],
            )
        ).first()
        total_days = (payload["end_date"] - payload["start_date"]).days + 1
        if leave_request is None:
            leave_request = LeaveRequest(
                employee_id=payload["employee_id"],
                leave_type=payload["leave_type"],
                start_date=payload["start_date"],
                end_date=payload["end_date"],
                total_days=total_days,
                reason=payload["reason"],
                status=payload["status"],
                hr_note=payload["hr_note"],
                handover_contact=payload["handover_contact"],
                handover_notes=payload["handover_notes"],
                urgency_level=payload["urgency_level"],
                privacy_flagged=payload["privacy_flagged"],
                transcript=payload["transcript"],
                submitted_at=payload["submitted_at"],
            )
        else:
            leave_request.leave_type = payload["leave_type"]
            leave_request.total_days = total_days
            leave_request.reason = payload["reason"]
            leave_request.status = payload["status"]
            leave_request.hr_note = payload["hr_note"]
            leave_request.handover_contact = payload["handover_contact"]
            leave_request.handover_notes = payload["handover_notes"]
            leave_request.urgency_level = payload["urgency_level"]
            leave_request.privacy_flagged = payload["privacy_flagged"]
            leave_request.transcript = payload["transcript"]
            if leave_request.submitted_at is None:
                leave_request.submitted_at = payload["submitted_at"]
        session.add(leave_request)
    session.commit()


def _ensure_leave_quotas(session: Session, employees: dict[str, Employee]) -> None:
    current_year = datetime.utcnow().year
    for employee in employees.values():
        quota = session.exec(
            select(LeaveQuota).where(
                LeaveQuota.employee_id == employee.id,
                LeaveQuota.year == current_year,
            )
        ).first()
        approved_leaves = session.exec(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.status == LeaveStatus.APPROVED,
            )
        ).all()

        annual_used = 0
        sick_used = 0
        casual_used = 0
        unpaid_used = 0
        for leave_request in approved_leaves:
            days = calculate_leave_days(leave_request)
            if leave_request.leave_type == LeaveType.ANNUAL:
                annual_used += days
            elif leave_request.leave_type == LeaveType.SICK:
                sick_used += days
            elif leave_request.leave_type == LeaveType.CASUAL:
                casual_used += days
            else:
                unpaid_used += days

        if quota is None:
            quota = LeaveQuota(
                employee_id=employee.id,
                year=current_year,
                annual_total=20,
                annual_used=annual_used,
                sick_total=10,
                sick_used=sick_used,
                casual_total=5,
                casual_used=casual_used,
                unpaid_used=unpaid_used,
            )
        else:
            quota.annual_total = 20
            quota.annual_used = annual_used
            quota.sick_total = 10
            quota.sick_used = sick_used
            quota.casual_total = 5
            quota.casual_used = casual_used
            quota.unpaid_used = unpaid_used
        session.add(quota)
    session.commit()
