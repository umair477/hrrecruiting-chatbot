from __future__ import annotations

from typing import Any, TypedDict

from hr_chatbot.leave_workflow import LeaveInterviewEngine
from hr_chatbot.recruitment_scorecard import build_scorecard
from app.services.recruitment_evaluator import evaluate_interview_answer

from app.core.database import clear_checkpoint, has_checkpoint, load_checkpoint, save_checkpoint

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - optional dependency fallback
    END = START = StateGraph = None


LEAVE_CHECKPOINT_WORKFLOW = "leave_management"


class LeaveAgentState(TypedDict):
    message: str
    employee_id: str
    engine: LeaveInterviewEngine
    response: dict[str, Any]


class RecruitmentAgentState(TypedDict):
    candidate_name: str
    role_title: str
    resume_text: str
    job_description: str
    screening_answers: list[str]
    scorecard: dict[str, Any]


class RecruitmentInterviewState(TypedDict):
    question: str
    answer: str
    job_description: str
    evaluation: dict[str, Any]


def _collect_leave_slots(state: LeaveAgentState) -> dict[str, Any]:
    return {
        "response": state["engine"].handle_message(
            state["message"],
            employee_id=state["employee_id"],
        )
    }


def has_leave_agent_state(thread_id: str) -> bool:
    return has_checkpoint(thread_id, workflow=LEAVE_CHECKPOINT_WORKFLOW)


def reset_leave_agent_state(thread_id: str) -> None:
    try:
        clear_checkpoint(thread_id, workflow=LEAVE_CHECKPOINT_WORKFLOW)
    except Exception:
        return


def run_leave_agent(
    engine: LeaveInterviewEngine,
    employee_id: str,
    message: str,
    *,
    thread_id: str,
) -> dict[str, Any]:
    checkpoint = load_checkpoint(thread_id, workflow=LEAVE_CHECKPOINT_WORKFLOW)
    if checkpoint:
        engine.restore_state(checkpoint)

    if StateGraph is None:
        response = engine.handle_message(message, employee_id=employee_id)
    else:
        graph = StateGraph(LeaveAgentState)
        graph.add_node("collect_slots", _collect_leave_slots)
        graph.add_edge(START, "collect_slots")
        graph.add_edge("collect_slots", END)
        compiled = graph.compile()
        result = compiled.invoke(
            {"message": message, "employee_id": employee_id, "engine": engine},
            config={"configurable": {"thread_id": thread_id}},
        )
        response = result["response"]

    try:
        save_checkpoint(
            thread_id,
            workflow=LEAVE_CHECKPOINT_WORKFLOW,
            state=engine.export_state(),
            event_type="turn",
        )
    except Exception:
        pass

    return response


def _score_recruitment_candidate(state: RecruitmentAgentState) -> dict[str, Any]:
    scorecard = build_scorecard(
        candidate_name=state["candidate_name"],
        role_title=state["role_title"],
        cv_text=state["resume_text"],
        job_description=state["job_description"],
        screening_answers=state["screening_answers"],
    )
    return {"scorecard": scorecard.as_dict()}


def _evaluate_recruitment_answer(state: RecruitmentInterviewState) -> dict[str, Any]:
    return {
        "evaluation": evaluate_interview_answer(
            question=state["question"],
            answer=state["answer"],
            job_description=state["job_description"],
        )
    }


def run_recruitment_agent(
    *,
    candidate_name: str,
    role_title: str,
    resume_text: str,
    job_description: str,
    screening_answers: list[str],
) -> dict[str, Any]:
    if StateGraph is None:
        return build_scorecard(
            candidate_name=candidate_name,
            role_title=role_title,
            cv_text=resume_text,
            job_description=job_description,
            screening_answers=screening_answers,
        ).as_dict()

    graph = StateGraph(RecruitmentAgentState)
    graph.add_node("score_candidate", _score_recruitment_candidate)
    graph.add_edge(START, "score_candidate")
    graph.add_edge("score_candidate", END)
    compiled = graph.compile()
    result = compiled.invoke(
        {
            "candidate_name": candidate_name,
            "role_title": role_title,
            "resume_text": resume_text,
            "job_description": job_description,
            "screening_answers": screening_answers,
        }
    )
    return result["scorecard"]


def run_recruitment_interviewer(*, question: str, answer: str, job_description: str) -> dict[str, Any]:
    if StateGraph is None:
        return evaluate_interview_answer(
            question=question,
            answer=answer,
            job_description=job_description,
        )

    graph = StateGraph(RecruitmentInterviewState)
    graph.add_node("evaluate_answer", _evaluate_recruitment_answer)
    graph.add_edge(START, "evaluate_answer")
    graph.add_edge("evaluate_answer", END)
    compiled = graph.compile()
    result = compiled.invoke(
        {
            "question": question,
            "answer": answer,
            "job_description": job_description,
        }
    )
    return result["evaluation"]
