from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.models import Job, JobStatus
from backend.app.schemas import (
    CandidateCVUploadResponse,
    CandidatePublicApplyRequest,
    CandidatePublicApplyResponse,
    CandidatePublicChatRequest,
    CandidatePublicChatResponse,
    CandidatePublicSubmitRequest,
    CandidatePublicSubmitResponse,
    PublicJobListingRead,
)
from backend.app.services.candidate_public import (
    extract_cv_summary_with_llm,
    extract_cv_text,
    finalize_candidate_application,
    is_valid_email,
    run_candidate_chat_turn,
    start_candidate_application_session,
    upsert_candidate_cv,
)


router = APIRouter(tags=["public-candidate"])


@router.get("/jobs/public", response_model=list[PublicJobListingRead])
def list_public_jobs(session: Session = Depends(get_session)) -> list[PublicJobListingRead]:
    jobs = session.exec(
        select(Job).where(Job.status == JobStatus.OPEN).order_by(Job.created_at.desc())
    ).all()
    return [PublicJobListingRead.model_validate(job) for job in jobs]


@router.post("/candidates/upload-cv", response_model=CandidateCVUploadResponse)
def upload_candidate_cv(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CandidateCVUploadResponse:
    normalized_email = email.strip().lower()
    if not is_valid_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address.")
    if not first_name.strip() or not last_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="First and last name are required.")

    raw_bytes = file.file.read()
    try:
        cv_text = extract_cv_text(filename=file.filename or "", raw_bytes=raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    extracted_summary = extract_cv_summary_with_llm(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=normalized_email,
        cv_text=cv_text,
    )
    candidate = upsert_candidate_cv(
        session=session,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=normalized_email,
        cv_text=cv_text,
        cv_summary_json=extracted_summary,
    )
    years = float(extracted_summary.get("total_years_experience", 0) or 0)
    top_skills = [
        str(skill).strip()
        for skill in extracted_summary.get("skills", [])
        if str(skill).strip()
    ][:3]

    return CandidateCVUploadResponse(
        candidate_id=int(candidate.id),
        full_name=f"{first_name.strip()} {last_name.strip()}".strip(),
        email=normalized_email,
        total_years_experience=years,
        top_skills=top_skills,
        extracted_summary=extracted_summary,
        reply=(
            f"Thanks! I've reviewed your CV. You have {years:g} years of experience "
            f"in {', '.join(top_skills) if top_skills else 'relevant skills'}. Let's proceed with a few screening questions."
        ),
    )


@router.post("/candidates/apply/{job_id}", response_model=CandidatePublicApplyResponse)
def start_candidate_application(
    job_id: int,
    payload: CandidatePublicApplyRequest,
    session: Session = Depends(get_session),
) -> CandidatePublicApplyResponse:
    try:
        candidate_session = start_candidate_application_session(
            session=session,
            job_id=job_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email.strip().lower(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    first_question = candidate_session.questions[0]["question_text"]
    return CandidatePublicApplyResponse(
        session_id=candidate_session.session_id,
        candidate_id=candidate_session.candidate_id,
        reply=(
            f"Hi there! 👋 I'm the Hiring Assistant for Talent Spark. You're applying for the position of "
            f"{candidate_session.job_title}. Question 1 of {len(candidate_session.questions)}: {first_question}"
        ),
        question_number=1,
        total_questions=len(candidate_session.questions),
    )


@router.post("/chat/candidate", response_model=CandidatePublicChatResponse)
def candidate_chat(
    payload: CandidatePublicChatRequest,
    session: Session = Depends(get_session),
) -> CandidatePublicChatResponse:
    try:
        result = run_candidate_chat_turn(
            session=session,
            session_id=payload.session_id,
            message=payload.message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CandidatePublicChatResponse(
        reply=result["reply"],
        question_number=int(result["question_number"]),
        total_questions=int(result["total_questions"]),
        requires_elaboration=bool(result["requires_elaboration"]),
        ready_for_submission=bool(result["ready_for_submission"]),
    )


@router.post("/candidates/submit", response_model=CandidatePublicSubmitResponse)
def submit_candidate_application(
    payload: CandidatePublicSubmitRequest,
    session: Session = Depends(get_session),
) -> CandidatePublicSubmitResponse:
    try:
        result = finalize_candidate_application(session=session, session_id=payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CandidatePublicSubmitResponse(
        reply=str(result["reply"]),
        submitted=bool(result["submitted"]),
    )
