from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi import UploadFile

from hr_chatbot.recruitment_scorecard import (
    Recommendation,
    extract_keywords,
    score_keyword_alignment,
)

from backend.app.models import Candidate, InterviewStatus
from backend.app.services.admin_dashboard import split_full_name
from backend.app.services.agentic import run_recruitment_agent, run_recruitment_interviewer
from backend.app.services.recruitment_skimmer import skim_candidate_profile

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - optional dependency fallback
    PdfReader = None


def parse_resume_file(upload: UploadFile) -> str:
    raw_bytes = upload.file.read()
    upload.file.seek(0)

    if upload.filename and upload.filename.lower().endswith(".pdf") and PdfReader is not None:
        reader = PdfReader(BytesIO(raw_bytes))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if extracted:
            return extracted

    return raw_bytes.decode("utf-8", errors="ignore").strip()


def normalize_screening_answers(raw_answers: str | None) -> list[str]:
    if not raw_answers:
        return []
    return [line.strip() for line in raw_answers.splitlines() if line.strip()]


def derive_skills(resume_text: str, job_description: str) -> list[str]:
    jd_keywords = extract_keywords(job_description)
    resume_lower = resume_text.lower()
    return [keyword for keyword in jd_keywords if keyword in resume_lower][:8]


def derive_resume_summary(*, resume_score: int, skills: list[str], skim_summary: str | None = None) -> str:
    if skim_summary:
        return (
            f"{skim_summary} Resume screening score is {resume_score}. "
            "Interview answers will refine the final recommendation."
        )
    if skills:
        return (
            f"Resume screening complete. Current resume match score is {resume_score}. "
            f"Key matched skills: {', '.join(skills[:5])}. Interview answers will refine the final recommendation."
        )
    return (
        f"Resume screening complete. Current resume match score is {resume_score}. "
        "Interview answers are needed to improve confidence in the recommendation."
    )


def build_resume_intake(candidate_name: str, role_title: str, resume_text: str, job_description: str) -> dict[str, Any]:
    skim = skim_candidate_profile(
        candidate_name=candidate_name,
        role_title=role_title,
        resume_text=resume_text,
        job_description=job_description,
    )
    resume_alignment = score_keyword_alignment(resume_text, job_description)
    resume_score = int(round((resume_alignment.score / 5) * 100))
    screening_questions = list(skim.get("screening_questions", []))
    skills = list(skim.get("matched_skills", []))[:8]
    skim_insights = list(skim.get("insights", []))
    risk_flags = list(skim.get("risk_flags", []))
    gaps = list(skim.get("gaps", []))
    recommendation = Recommendation.YES.value if resume_score >= 75 else Recommendation.MAYBE.value if resume_score >= 55 else Recommendation.NO.value
    return {
        "candidate_name": candidate_name,
        "role_title": role_title,
        "resume_score": resume_score,
        "skim_insights": skim_insights,
        "screening_questions": screening_questions,
        "skills": skills,
        "summary": derive_resume_summary(
            resume_score=resume_score,
            skills=skills,
            skim_summary=str(skim.get("summary", "")).strip() or None,
        ),
        "scorecard": {
            "resume_score": resume_score,
            "overall_suitability_score": resume_score,
            "recommendation": recommendation,
            "skill_alignment": {"score": resume_alignment.score, "evidence": resume_alignment.evidence},
            "skim_insights": skim_insights,
            "gap_signals": gaps,
            "risk_flags": risk_flags,
            "recommended_follow_up_questions": screening_questions,
            "transcript_summary": "",
            "interview_score": 0,
            "skim_source": skim.get("source", "heuristic"),
        },
    }


def initialize_candidate_interview(
    candidate: Candidate,
    *,
    candidate_name: str,
    role_title: str,
    resume_text: str,
    job_description: str,
    screening_answers: list[str],
) -> dict[str, Any]:
    intake = build_resume_intake(candidate_name, role_title, resume_text, job_description)
    first_name, last_name = split_full_name(candidate_name)
    candidate.name = candidate_name
    candidate.first_name = first_name
    candidate.last_name = last_name
    candidate.role_title = role_title
    candidate.resume_text = resume_text
    candidate.job_description = job_description
    candidate.cv_summary = str(intake["summary"])
    candidate.resume_score = int(intake["resume_score"])
    candidate.interview_score = 0
    candidate.ai_score = int(intake["resume_score"])
    candidate.skim_insights = list(intake["skim_insights"])
    candidate.screening_questions = list(intake["screening_questions"])
    candidate.screening_transcript = []
    candidate.skills = list(intake["skills"])
    candidate.summary = str(intake["summary"])
    candidate.raw_answers = []
    candidate.current_question_index = 0
    candidate.interview_status = (
        InterviewStatus.COMPLETED if not candidate.screening_questions else InterviewStatus.IN_PROGRESS
    )

    for answer in screening_answers:
        submit_interview_answer(candidate, answer)

    return {
        "scorecard": {
            **intake["scorecard"],
            "overall_suitability_score": candidate.ai_score,
            "interview_score": candidate.interview_score,
            "transcript_summary": " ".join(
                entry["answer"] for entry in candidate.raw_answers if isinstance(entry, dict) and entry.get("answer")
            ),
        },
        "summary": candidate.summary,
        "cv_summary": candidate.cv_summary,
        "skills": candidate.skills,
        "skim_insights": candidate.skim_insights,
    }


def submit_interview_answer(candidate: Candidate, answer: str) -> dict[str, Any]:
    if candidate.current_question_index >= len(candidate.screening_questions):
        return {
            "question": "",
            "answer": answer,
            "score": max(candidate.interview_score // 10, 1) if candidate.interview_score else 1,
            "justification": "Interview already completed.",
            "source": "system",
        }

    current_question = candidate.screening_questions[candidate.current_question_index]
    evaluation = run_recruitment_interviewer(
        question=current_question,
        answer=answer,
        job_description=candidate.job_description,
    )
    candidate.raw_answers = [
        *candidate.raw_answers,
        {
            "question": current_question,
            "answer": answer,
            "score": int(evaluation["score"]),
            "justification": str(evaluation["justification"]),
            "source": str(evaluation["source"]),
        },
    ]
    candidate.current_question_index += 1
    candidate.interview_status = (
        InterviewStatus.COMPLETED
        if candidate.current_question_index >= len(candidate.screening_questions)
        else InterviewStatus.IN_PROGRESS
    )
    candidate.interview_score = calculate_interview_score(candidate.raw_answers)
    candidate.ai_score = calculate_candidate_score(candidate.resume_score, candidate.raw_answers)
    candidate.summary = derive_interview_summary(candidate)
    return {
        "question": current_question,
        "answer": answer,
        "score": int(evaluation["score"]),
        "justification": str(evaluation["justification"]),
        "source": str(evaluation["source"]),
    }


def calculate_interview_score(raw_answers: list[dict[str, Any]]) -> int:
    numeric_scores = [int(entry["score"]) for entry in raw_answers if isinstance(entry, dict) and entry.get("score") is not None]
    if not numeric_scores:
        return 0
    average = sum(numeric_scores) / len(numeric_scores)
    return int(round((average / 10) * 100))


def calculate_candidate_score(resume_score: int, raw_answers: list[dict[str, Any]]) -> int:
    interview_score = calculate_interview_score(raw_answers)
    if interview_score == 0:
        return resume_score
    return int(round((resume_score * 0.4) + (interview_score * 0.6)))


def derive_interview_summary(candidate: Candidate) -> str:
    if not candidate.raw_answers:
        skim_summary = " ".join(candidate.skim_insights[:2]) if candidate.skim_insights else None
        return derive_resume_summary(resume_score=candidate.resume_score, skills=candidate.skills, skim_summary=skim_summary)

    answer_bits = []
    for entry in candidate.raw_answers[-2:]:
        if isinstance(entry, dict):
            answer_bits.append(str(entry.get("justification", "")).strip())

    status_text = (
        "Interview completed."
        if candidate.interview_status == InterviewStatus.COMPLETED
        else f"Interview in progress with {candidate.current_question_index} of {len(candidate.screening_questions)} answers submitted."
    )
    evaluation_text = " ".join(bit for bit in answer_bits if bit)
    return (
        f"{status_text} Resume score {candidate.resume_score}, interview score {candidate.interview_score}, "
        f"combined match {candidate.ai_score}. {evaluation_text}"
    ).strip()


def build_candidate_interview_payload(candidate: Candidate) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "next_question": get_current_question(candidate),
    }


def get_current_question(candidate: Candidate) -> str | None:
    if candidate.current_question_index >= len(candidate.screening_questions):
        return None
    return candidate.screening_questions[candidate.current_question_index]


def hydrate_legacy_candidate(candidate: Candidate) -> bool:
    changed = False
    if not candidate.screening_questions and candidate.screening_transcript:
        candidate.screening_questions = list(candidate.screening_transcript)
        changed = True
    if candidate.skim_insights is None:
        candidate.skim_insights = []
        changed = True
    if not candidate.first_name or candidate.last_name is None:
        first_name, last_name = split_full_name(candidate.name)
        candidate.first_name = first_name
        candidate.last_name = last_name
        changed = True
    if not candidate.cv_summary and candidate.summary:
        candidate.cv_summary = candidate.summary
        changed = True
    if candidate.resume_score == 0 and candidate.ai_score > 0:
        candidate.resume_score = candidate.ai_score
        changed = True
    if candidate.raw_answers is None:
        candidate.raw_answers = []
        changed = True
    if candidate.current_question_index > len(candidate.screening_questions):
        candidate.current_question_index = len(candidate.screening_questions)
        changed = True
    if candidate.interview_status == InterviewStatus.PENDING and candidate.screening_questions:
        candidate.interview_status = (
            InterviewStatus.COMPLETED
            if candidate.current_question_index >= len(candidate.screening_questions)
            else InterviewStatus.IN_PROGRESS
        )
        changed = True
    return changed


def build_legacy_scorecard(
    *,
    candidate_name: str,
    role_title: str,
    resume_text: str,
    job_description: str,
    screening_answers: list[str],
) -> dict[str, Any]:
    return run_recruitment_agent(
        candidate_name=candidate_name,
        role_title=role_title,
        resume_text=resume_text,
        job_description=job_description,
        screening_answers=screening_answers,
    )
