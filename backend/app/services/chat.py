from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from hr_chatbot.leave_workflow import LeaveBalanceResult, LeaveInterviewEngine
from hr_chatbot.router import Workflow, classify_workflow

from app.models import Candidate, Employee, InterviewStatus, LeaveRequest, LeaveStatus, User
from app.schemas import ChatSocketOutbound
from app.services.agentic import has_leave_agent_state, reset_leave_agent_state, run_leave_agent
from app.services.leave import get_leave_balance_summary, get_approved_leave_days
from app.services.recruitment import get_current_question, submit_interview_answer


@dataclass
class ChatRuntime:
    user: User
    thread_id: str
    leave_engine: LeaveInterviewEngine | None = None
    workflow: Workflow | None = None


def _balance_checker_for_employee(employee: Employee, session: Session):
    def _checker(draft) -> LeaveBalanceResult:
        if draft.start_date is None or draft.end_date is None:
            current_remaining = get_leave_balance_summary(session, employee)["remaining"]
            return LeaveBalanceResult(
                has_balance=False,
                remaining_days=float(current_remaining),
                note="Dates are missing.",
            )

        approved_days = get_approved_leave_days(session, employee.id)
        current_remaining = max(float(employee.annual_allowance) - float(approved_days), 0.0)
        days_requested = (draft.end_date - draft.start_date).days + 1
        return LeaveBalanceResult(
            has_balance=current_remaining >= days_requested,
            remaining_days=current_remaining,
            note="Balance evaluated against approved leave history and annual allowance.",
        )

    return _checker


def _persist_leave_request(report: dict[str, object], employee: Employee, session: Session) -> LeaveRequest:
    leave_request = LeaveRequest(
        employee_id=employee.id,
        start_date=date.fromisoformat(str(report["start_date"])),
        end_date=date.fromisoformat(str(report["end_date"])),
        reason=str(report["reason_summary"]),
        status=LeaveStatus.PENDING,
        handover_contact=str(report["handover_contact"] or ""),
        handover_notes=str(report["handover_plan"] or ""),
        urgency_level=str(report["urgency_level"] or "medium"),
        privacy_flagged=bool(report["privacy_flagged"]),
        transcript=report.get("transcript", []),
    )
    session.add(leave_request)
    session.commit()
    session.refresh(leave_request)
    return leave_request


def handle_chat_turn(runtime: ChatRuntime, message: str, session: Session) -> ChatSocketOutbound:
    employee = None
    candidate = None
    if runtime.user.employee_id is not None:
        employee = session.exec(select(Employee).where(Employee.id == runtime.user.employee_id)).first()
    if runtime.user.candidate_id is not None:
        candidate = session.exec(select(Candidate).where(Candidate.id == runtime.user.candidate_id)).first()

    if runtime.workflow is None:
        if has_leave_agent_state(runtime.thread_id):
            runtime.workflow = Workflow.LEAVE_MANAGEMENT
        elif candidate is not None and candidate.interview_status != InterviewStatus.COMPLETED:
            runtime.workflow = Workflow.RECRUITMENT_SCREENING
        else:
            runtime.workflow = classify_workflow(message).workflow

    if runtime.workflow == Workflow.LEAVE_MANAGEMENT and employee is not None:
        if runtime.leave_engine is None:
            runtime.leave_engine = LeaveInterviewEngine(
                balance_checker=_balance_checker_for_employee(employee, session)
            )

        response = run_leave_agent(
            runtime.leave_engine,
            str(employee.id),
            message,
            thread_id=runtime.thread_id,
        )
        report = response.get("structured_report")
        if report and not session.exec(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.start_date == date.fromisoformat(str(report["start_date"])),
                LeaveRequest.end_date == date.fromisoformat(str(report["end_date"])),
                LeaveRequest.reason == str(report["reason_summary"]),
            )
        ).first():
            _persist_leave_request(report, employee, session)
        if report:
            reset_leave_agent_state(runtime.thread_id)
            runtime.leave_engine = None
            runtime.workflow = None

        return ChatSocketOutbound(
            thread_id=runtime.thread_id,
            workflow=Workflow.LEAVE_MANAGEMENT.value,
            reply=str(response["reply"]),
            missing_slots=list(response.get("missing_slots", [])),
            privacy_note=response.get("privacy_note"),
            structured_report=report,
        )

    if runtime.workflow == Workflow.RECRUITMENT_SCREENING and candidate is not None:
        if not candidate.screening_questions:
            return ChatSocketOutbound(
                thread_id=runtime.thread_id,
                workflow=Workflow.RECRUITMENT_SCREENING.value,
                reply="Your interview session has not been initialized yet. Please ask HR to start the recruitment interview from the dashboard.",
                missing_slots=[],
            )

        evaluation = submit_interview_answer(candidate, message)
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
        next_question = get_current_question(candidate)
        if next_question:
            reply = (
                f"Thanks. I scored that answer {evaluation['score']}/10. {evaluation['justification']} "
                f"Next question: {next_question}"
            )
        else:
            reply = (
                f"Thanks. I scored that answer {evaluation['score']}/10. {evaluation['justification']} "
                f"Interview complete. Your current combined match score is {candidate.ai_score}."
            )

        return ChatSocketOutbound(
            thread_id=runtime.thread_id,
            workflow=Workflow.RECRUITMENT_SCREENING.value,
            reply=reply,
            missing_slots=[],
            structured_report={
                "evaluation": evaluation,
                "interview_status": candidate.interview_status.value,
                "resume_score": candidate.resume_score,
                "interview_score": candidate.interview_score,
                "ai_score": candidate.ai_score,
                "next_question": next_question,
            },
        )

    if runtime.workflow == Workflow.RECRUITMENT_SCREENING:
        return ChatSocketOutbound(
            thread_id=runtime.thread_id,
            workflow=Workflow.RECRUITMENT_SCREENING.value,
            reply=(
                "I can help with recruitment screening. Upload a resume and job description from the "
                "Recruitment Hub to generate a scorecard, then I can guide the behavioral screening."
            ),
            missing_slots=[],
        )

    return ChatSocketOutbound(
        thread_id=runtime.thread_id,
        workflow=Workflow.UNKNOWN.value,
        reply=(
            "I can help with leave requests or recruitment screening. Try saying 'I want leave next Tuesday' "
            "or upload a candidate resume from the Recruitment Hub."
        ),
        missing_slots=[],
    )
