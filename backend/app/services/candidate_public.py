from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
import json
import re
from threading import Lock
from typing import Any
from urllib import error, request
from uuid import uuid4

from sqlmodel import Session, select

from backend.app.core.config import settings
from backend.app.models import Candidate, CandidateStatus, InterviewStatus, Job, JobStatus

try:
    import pdfplumber
except ImportError:  # pragma: no cover - optional dependency fallback
    pdfplumber = None

try:
    from docx import Document
except ImportError:  # pragma: no cover - optional dependency fallback
    Document = None

try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - optional dependency fallback
    PdfReader = None


MAX_CV_SIZE_BYTES = 5 * 1024 * 1024
ALLOWED_CV_EXTENSIONS = (".pdf", ".docx")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class CandidateChatSession:
    session_id: str
    candidate_id: int
    job_id: int
    job_title: str
    email: str
    first_name: str
    questions: list[dict[str, Any]]
    answers: list[dict[str, Any]] = field(default_factory=list)
    current_question_index: int = 0
    awaiting_followup: bool = False
    pending_answer: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


_SESSION_STORE: dict[str, CandidateChatSession] = {}
_SESSION_LOCK = Lock()


def is_valid_email(email: str) -> bool:
    return EMAIL_PATTERN.match(email.strip()) is not None


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    output = payload.get("output", [])
    for item in output:
        for content in item.get("content", []):
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                return text_value.strip()

    raise ValueError("No text output found in OpenAI response.")


def _call_openai_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    api_key = settings.openai_api_key.strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    payload = {
        "model": model,
        "input": [
            {"role": "developer", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    }
    http_request = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=50) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI request failed with status {exc.code}: {body}") from exc
    return json.loads(_extract_response_text(response_payload))


def _extract_pdf_text(raw_bytes: bytes) -> str:
    if pdfplumber is not None:
        with pdfplumber.open(BytesIO(raw_bytes)) as pdf:
            extracted = "\n".join((page.extract_text() or "").strip() for page in pdf.pages).strip()
            if extracted:
                return extracted

    if PdfReader is not None:
        reader = PdfReader(BytesIO(raw_bytes))
        extracted = "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
        if extracted:
            return extracted

    return ""


def _extract_docx_text(raw_bytes: bytes) -> str:
    if Document is None:
        return ""
    document = Document(BytesIO(raw_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()).strip()


def extract_cv_text(*, filename: str, raw_bytes: bytes) -> str:
    file_name = filename.strip().lower()
    if not file_name.endswith(ALLOWED_CV_EXTENSIONS):
        raise ValueError("Only PDF and DOCX files are supported.")
    if len(raw_bytes) > MAX_CV_SIZE_BYTES:
        raise ValueError("CV file exceeds the 5MB size limit.")

    if file_name.endswith(".pdf"):
        extracted = _extract_pdf_text(raw_bytes)
    else:
        extracted = _extract_docx_text(raw_bytes)

    if not extracted.strip():
        # Last-resort fallback to preserve a useful failure mode for unusual encodings.
        extracted = raw_bytes.decode("utf-8", errors="ignore").strip()
    if not extracted:
        raise ValueError("Unable to extract text from the uploaded CV.")
    return extracted


def extract_cv_summary_with_llm(
    *,
    first_name: str,
    last_name: str,
    email: str,
    cv_text: str,
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "full_name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "total_years_experience": {"type": "number"},
            "education": {"type": "array", "items": {"type": "string"}},
            "skills": {"type": "array", "items": {"type": "string"}},
            "work_experience": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"},
                        "title": {"type": "string"},
                        "duration": {"type": "string"},
                        "responsibilities": {"type": "string"},
                    },
                    "required": ["company", "title", "duration", "responsibilities"],
                    "additionalProperties": False,
                },
            },
            "certifications": {"type": "array", "items": {"type": "string"}},
            "languages": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "full_name",
            "email",
            "phone",
            "total_years_experience",
            "education",
            "skills",
            "work_experience",
            "certifications",
            "languages",
        ],
        "additionalProperties": False,
    }
    try:
        return _call_openai_json(
            model=settings.openai_recruitment_model,
            system_prompt=(
                "Extract structured details from CV text. Return strict JSON only. "
                "Do not invent details that are not present in the CV."
            ),
            user_prompt=(
                "Extract the following from this CV in JSON format: "
                "full_name, email, phone, total_years_experience, education (list), "
                "skills (list), work_experience (list of: company, title, duration, responsibilities), "
                f"certifications (list), languages (list).\n\nCV text:\n{cv_text}\n\n"
                f"Known applicant details:\nFirst Name: {first_name}\nLast Name: {last_name}\nEmail: {email}"
            ),
            schema_name="candidate_cv_extract",
            schema=schema,
        )
    except Exception as exc:
        raise RuntimeError("CV extraction failed. OpenAI response could not be generated or parsed.") from exc


def upsert_candidate_cv(
    *,
    session: Session,
    first_name: str,
    last_name: str,
    email: str,
    cv_text: str,
    cv_summary_json: dict[str, Any],
) -> Candidate:
    candidate = session.exec(select(Candidate).where(Candidate.email == email)).first()
    if candidate is None:
        candidate = Candidate(
            first_name=first_name,
            last_name=last_name,
            name=f"{first_name} {last_name}".strip(),
            email=email,
            job_id=None,
            role_title="Applicant",
            resume_text=cv_text,
            cv_extracted_json=cv_summary_json,
            cv_summary="CV received for public application workflow.",
            skills=[str(skill).strip() for skill in cv_summary_json.get("skills", []) if str(skill).strip()][:10],
            status=CandidateStatus.UNDER_REVIEW,
            interview_status=InterviewStatus.PENDING,
            applied_at=datetime.utcnow(),
        )
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        candidate.name = f"{first_name} {last_name}".strip()
        candidate.email = email
        candidate.resume_text = cv_text
        candidate.cv_extracted_json = cv_summary_json
        candidate.cv_summary = "CV received for public application workflow."
        candidate.skills = [
            str(skill).strip() for skill in cv_summary_json.get("skills", []) if str(skill).strip()
        ][:10]
        candidate.applied_at = datetime.utcnow()

    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def generate_screening_questions(*, job: Job, cv_summary: dict[str, Any]) -> list[dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 6,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "integer"},
                        "question_text": {"type": "string"},
                        "category": {
                            "type": "string",
                            "enum": ["technical", "experience", "behavioral", "motivation"],
                        },
                        "max_score": {"type": "integer"},
                    },
                    "required": ["question_id", "question_text", "category", "max_score"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    }
    try:
        payload = _call_openai_json(
            model=settings.openai_recruitment_model,
            system_prompt="You are an HR screening interviewer. Return strict JSON only.",
            user_prompt=(
                "Generate exactly 6 screening interview questions:\n"
                "- 2 about technical skills relevant to the job\n"
                "- 2 about past experience and achievements\n"
                "- 1 situational/behavioral question\n"
                "- 1 motivation/culture-fit question\n"
                "Return as JSON with this shape:\n"
                "{ \"questions\": [{ question_id, question_text, category, max_score }] }\n"
                "where max_score for each question = 10.\n\n"
                f"Job Title: {job.title}\n"
                f"Job Requirements: required_skills={job.required_skills}, "
                f"experience_years={job.experience_years}, responsibilities={job.responsibilities}\n"
                f"Candidate CV Summary: {json.dumps(cv_summary, default=str)}"
            ),
            schema_name="candidate_screening_questions",
            schema=schema,
        )
        questions = payload.get("questions", []) if isinstance(payload, dict) else payload
        if not isinstance(questions, list):
            raise ValueError("LLM returned invalid question structure.")

        cleaned: list[dict[str, Any]] = []
        for idx, entry in enumerate(questions[:6], start=1):
            if not isinstance(entry, dict):
                continue
            text_value = str(entry.get("question_text", "")).strip()
            if not text_value:
                continue
            cleaned.append(
                {
                    "question_id": idx,
                    "question_text": text_value,
                    "category": str(entry.get("category", "general")).strip() or "general",
                    "max_score": 10,
                }
            )
        if len(cleaned) == 6:
            return cleaned
        raise ValueError("LLM returned fewer than 6 valid questions.")
    except Exception as exc:
        raise RuntimeError("Question generation failed. OpenAI response could not be generated or parsed.") from exc


def start_candidate_application_session(
    *,
    session: Session,
    job_id: int,
    first_name: str,
    last_name: str,
    email: str,
) -> CandidateChatSession:
    if not is_valid_email(email):
        raise ValueError("Please provide a valid email address.")

    job = session.exec(select(Job).where(Job.job_id == job_id, Job.status == JobStatus.OPEN)).first()
    if job is None:
        raise ValueError("Selected job is not available for applications.")

    candidate = session.exec(select(Candidate).where(Candidate.email == email)).first()
    if candidate is None:
        raise ValueError("Please upload your CV before starting the application chat.")
    if not candidate.resume_text.strip():
        raise ValueError("Please upload your CV before starting the application chat.")

    cv_summary = candidate.cv_extracted_json or {}
    questions = generate_screening_questions(job=job, cv_summary=cv_summary)

    candidate.first_name = first_name.strip()
    candidate.last_name = last_name.strip()
    candidate.name = f"{first_name.strip()} {last_name.strip()}".strip()
    candidate.email = email.strip().lower()
    candidate.job_id = int(job.job_id)
    candidate.role_title = job.title
    candidate.job_description = job.description
    candidate.screening_questions = [str(item["question_text"]) for item in questions]
    candidate.interview_status = InterviewStatus.IN_PROGRESS
    candidate.current_question_index = 0
    candidate.interview_transcript = []
    candidate.raw_answers = []
    candidate.status = CandidateStatus.UNDER_REVIEW
    candidate.applied_at = datetime.utcnow()
    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    candidate_session = CandidateChatSession(
        session_id=uuid4().hex,
        candidate_id=int(candidate.id),
        job_id=int(job.job_id),
        job_title=job.title,
        email=candidate.email,
        first_name=candidate.first_name or first_name.strip(),
        questions=questions,
    )
    with _SESSION_LOCK:
        _SESSION_STORE[candidate_session.session_id] = candidate_session
    return candidate_session


def _save_progress(session: Session, chat_session: CandidateChatSession) -> None:
    candidate = session.get(Candidate, chat_session.candidate_id)
    if candidate is None:
        return
    candidate.interview_transcript = chat_session.answers
    candidate.current_question_index = chat_session.current_question_index
    candidate.raw_answers = [
        {
            "question": answer["question_text"],
            "answer": answer["answer"],
            "score": 0,
            "justification": "",
            "source": "public_chat",
        }
        for answer in chat_session.answers
    ]
    session.add(candidate)
    session.commit()


def _record_answer(session: Session, chat_session: CandidateChatSession, answer_text: str) -> None:
    current_question = chat_session.questions[chat_session.current_question_index]
    chat_session.answers.append(
        {
            "question_id": int(current_question["question_id"]),
            "question_text": str(current_question["question_text"]),
            "category": str(current_question["category"]),
            "max_score": 10,
            "answer": answer_text.strip(),
        }
    )
    chat_session.current_question_index += 1
    _save_progress(session, chat_session)


def run_candidate_chat_turn(
    *,
    session: Session,
    session_id: str,
    message: str,
) -> dict[str, Any]:
    with _SESSION_LOCK:
        chat_session = _SESSION_STORE.get(session_id)
    if chat_session is None:
        raise ValueError("Session expired or not found. Please restart your application.")

    candidate_message = message.strip()
    if not candidate_message:
        raise ValueError("Message cannot be empty.")

    total_questions = len(chat_session.questions)
    if chat_session.current_question_index >= total_questions:
        return {
            "reply": "You have completed all screening questions. Please submit your application.",
            "question_number": total_questions,
            "total_questions": total_questions,
            "requires_elaboration": False,
            "ready_for_submission": True,
        }

    if chat_session.awaiting_followup:
        combined_answer = f"{chat_session.pending_answer} {candidate_message}".strip()
        chat_session.awaiting_followup = False
        chat_session.pending_answer = ""
        _record_answer(session, chat_session, combined_answer)
    else:
        if len(candidate_message.split()) < 15:
            chat_session.awaiting_followup = True
            chat_session.pending_answer = candidate_message
            return {
                "reply": "Could you elaborate a bit more on that?",
                "question_number": chat_session.current_question_index + 1,
                "total_questions": total_questions,
                "requires_elaboration": True,
                "ready_for_submission": False,
            }
        _record_answer(session, chat_session, candidate_message)

    if chat_session.current_question_index >= total_questions:
        candidate = session.get(Candidate, chat_session.candidate_id)
        if candidate is not None:
            candidate.interview_status = InterviewStatus.COMPLETED
            session.add(candidate)
            session.commit()
        return {
            "reply": (
                "Thanks, you have completed Question 6 of 6. I have everything needed for evaluation. "
                "Submitting your application now..."
            ),
            "question_number": total_questions,
            "total_questions": total_questions,
            "requires_elaboration": False,
            "ready_for_submission": True,
        }

    next_question = chat_session.questions[chat_session.current_question_index]
    return {
        "reply": (
            f"Question {chat_session.current_question_index + 1} of {total_questions}: "
            f"{next_question['question_text']}"
        ),
        "question_number": chat_session.current_question_index + 1,
        "total_questions": total_questions,
        "requires_elaboration": False,
        "ready_for_submission": False,
    }


def evaluate_candidate_screening(
    *,
    job: Job,
    cv_summary: dict[str, Any],
    interview_qa: list[dict[str, Any]],
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "integer"},
                        "score": {"type": "integer", "minimum": 0, "maximum": 10},
                        "brief_justification": {"type": "string"},
                    },
                    "required": ["question_id", "score", "brief_justification"],
                    "additionalProperties": False,
                },
            },
            "total_score": {"type": "number"},
            "percentage_score": {"type": "number"},
            "overall_summary": {"type": "string"},
            "recommendation": {
                "type": "string",
                "enum": ["Highly Recommended", "Recommended", "Needs Review", "Not Recommended"],
            },
        },
        "required": ["scores", "total_score", "percentage_score", "overall_summary", "recommendation"],
        "additionalProperties": False,
    }
    try:
        return _call_openai_json(
            model=settings.openai_evaluator_model,
            system_prompt="You are an objective HR evaluator. Return strict JSON only.",
            user_prompt=(
                "Score each answer from 0-10 based on relevance, depth/clarity, and alignment with job requirements. "
                "Return the requested JSON structure.\n\n"
                f"Job Requirements: title={job.title}, required_skills={job.required_skills}, "
                f"experience_years={job.experience_years}, responsibilities={job.responsibilities}\n"
                f"Candidate CV: {json.dumps(cv_summary, default=str)}\n"
                f"Interview Q&A: {json.dumps(interview_qa, default=str)}"
            ),
            schema_name="candidate_screening_evaluation",
            schema=schema,
        )
    except Exception as exc:
        raise RuntimeError("Screening evaluation failed. OpenAI response could not be generated or parsed.") from exc


def _status_for_recommendation(recommendation: str) -> CandidateStatus:
    if recommendation in {"Highly Recommended", "Recommended"}:
        return CandidateStatus.SHORTLISTED
    if recommendation == "Not Recommended":
        return CandidateStatus.REJECTED
    return CandidateStatus.UNDER_REVIEW


def finalize_candidate_application(*, session: Session, session_id: str) -> dict[str, Any]:
    with _SESSION_LOCK:
        chat_session = _SESSION_STORE.get(session_id)
    if chat_session is None:
        raise ValueError("Session expired or not found. Please restart your application.")

    if len(chat_session.answers) < len(chat_session.questions):
        raise ValueError("Interview is not complete yet. Please answer all screening questions first.")

    candidate = session.get(Candidate, chat_session.candidate_id)
    if candidate is None:
        raise ValueError("Candidate record not found.")
    job = session.get(Job, chat_session.job_id)
    if job is None:
        raise ValueError("Selected job no longer exists.")

    evaluation = evaluate_candidate_screening(
        job=job,
        cv_summary=candidate.cv_extracted_json or {},
        interview_qa=chat_session.answers,
    )

    score_rows = {int(item["question_id"]): item for item in evaluation.get("scores", []) if isinstance(item, dict)}
    scored_transcript: list[dict[str, Any]] = []
    raw_answers: list[dict[str, Any]] = []
    for answer in chat_session.answers:
        score_row = score_rows.get(int(answer["question_id"]), {"score": 0, "brief_justification": ""})
        scored_entry = {
            **answer,
            "score": int(score_row.get("score", 0)),
            "brief_justification": str(score_row.get("brief_justification", "")),
        }
        scored_transcript.append(scored_entry)
        raw_answers.append(
            {
                "question": str(answer["question_text"]),
                "answer": str(answer["answer"]),
                "score": int(score_row.get("score", 0)),
                "justification": str(score_row.get("brief_justification", "")),
                "source": "public_candidate_chat",
            }
        )

    percentage = float(evaluation.get("percentage_score", 0))
    recommendation = str(evaluation.get("recommendation", "Needs Review"))
    candidate.interview_transcript = scored_transcript
    candidate.raw_answers = raw_answers
    candidate.interview_score = int(round(percentage))
    candidate.screening_score = percentage
    candidate.ai_score = int(round(percentage))
    candidate.recommendation_label = recommendation
    candidate.summary = str(evaluation.get("overall_summary", "")).strip()
    candidate.status = _status_for_recommendation(recommendation)
    candidate.interview_status = InterviewStatus.COMPLETED
    candidate.current_question_index = len(chat_session.questions)
    candidate.applied_at = datetime.utcnow()
    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    with _SESSION_LOCK:
        _SESSION_STORE.pop(session_id, None)

    closing_message = (
        f"Thank you, {chat_session.first_name}! 🎉 Your application for {chat_session.job_title} has been "
        f"successfully submitted. Our HR team will review your profile and get back to you at "
        f"{chat_session.email} within 5–7 business days. Good luck!"
    )
    return {"reply": closing_message, "submitted": True}
