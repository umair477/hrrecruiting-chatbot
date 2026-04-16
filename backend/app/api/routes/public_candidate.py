from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.core.database import engine, get_session
from app.models import CandidateAsyncJob, Job, JobStatus
from app.schemas import (
    CandidateCVUploadResponse,
    CandidateAsyncJobResponse,
    CandidateAsyncJobStatusResponse,
    CandidatePublicApplyRequest,
    CandidatePublicApplyResponse,
    CandidatePublicChatRequest,
    CandidatePublicChatResponse,
    CandidatePublicSubmitRequest,
    CandidatePublicSubmitResponse,
    PublicJobListingRead,
)
from app.services.candidate_public import (
    extract_cv_summary_with_llm,
    extract_cv_text,
    finalize_candidate_application,
    is_valid_email,
    run_candidate_chat_turn,
    start_candidate_application_session,
    upsert_candidate_cv,
)
from app.services.idempotency import IdempotencyConflictError, fetch_record, payload_hash, save_record


router = APIRouter(tags=["public-candidate"])


def _process_cv_upload_job(async_job_id: str) -> None:
    with Session(engine) as background_session:
        async_job = background_session.exec(
            select(CandidateAsyncJob).where(CandidateAsyncJob.job_id == async_job_id)
        ).first()
        if async_job is None:
            return

        try:
            async_job.status = "processing"
            async_job.updated_at = datetime.utcnow()
            background_session.add(async_job)
            background_session.commit()

            payload = async_job.payload
            raw_bytes = bytes.fromhex(str(payload.get("file_hex", "")))
            cv_text = extract_cv_text(filename=str(payload.get("filename", "")), raw_bytes=raw_bytes)
            extracted_summary = extract_cv_summary_with_llm(
                first_name=str(payload.get("first_name", "")),
                last_name=str(payload.get("last_name", "")),
                email=str(payload.get("email", "")),
                cv_text=cv_text,
            )
            candidate = upsert_candidate_cv(
                session=background_session,
                first_name=str(payload.get("first_name", "")),
                last_name=str(payload.get("last_name", "")),
                email=str(payload.get("email", "")),
                cv_text=cv_text,
                cv_summary_json=extracted_summary,
            )
            async_job.status = "completed"
            async_job.candidate_id = candidate.id
            async_job.result = {
                "candidate_id": int(candidate.id),
                "email": str(payload.get("email", "")),
                "top_skills": extracted_summary.get("skills", []),
            }
            async_job.updated_at = datetime.utcnow()
            background_session.add(async_job)
            background_session.commit()
        except Exception as exc:
            async_job.status = "failed"
            async_job.error_message = str(exc)
            async_job.updated_at = datetime.utcnow()
            background_session.add(async_job)
            background_session.commit()


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


@router.post("/candidates/upload-cv/async", response_model=CandidateAsyncJobResponse)
def upload_candidate_cv_async(
    background_tasks: BackgroundTasks,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CandidateAsyncJobResponse:
    normalized_email = email.strip().lower()
    if not is_valid_email(normalized_email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address.")

    raw_bytes = file.file.read()
    async_job = CandidateAsyncJob(
        status="queued",
        payload={
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": normalized_email,
            "filename": file.filename or "",
            "file_hex": raw_bytes.hex(),
        },
    )
    session.add(async_job)
    session.commit()
    session.refresh(async_job)
    background_tasks.add_task(_process_cv_upload_job, async_job.job_id)
    return CandidateAsyncJobResponse(async_job_id=async_job.job_id, status=async_job.status)


@router.get("/candidates/jobs/{async_job_id}", response_model=CandidateAsyncJobStatusResponse)
def get_candidate_async_job(async_job_id: str, session: Session = Depends(get_session)) -> CandidateAsyncJobStatusResponse:
    async_job = session.exec(select(CandidateAsyncJob).where(CandidateAsyncJob.job_id == async_job_id)).first()
    if async_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Async job not found.")
    return CandidateAsyncJobStatusResponse(
        async_job_id=async_job.job_id,
        status=async_job.status,
        candidate_id=async_job.candidate_id,
        result=async_job.result,
        error_message=async_job.error_message,
    )


@router.post("/candidates/apply/{job_id}", response_model=CandidatePublicApplyResponse)
def start_candidate_application(
    job_id: int,
    payload: CandidatePublicApplyRequest,
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    session: Session = Depends(get_session),
) -> CandidatePublicApplyResponse:
    request_payload = {
        "job_id": job_id,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "email": payload.email.strip().lower(),
    }
    if idempotency_key:
        request_digest = payload_hash(request_payload)
        existing = fetch_record(session=session, idempotency_key=idempotency_key)
        if existing:
            if existing.request_hash != request_digest:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key reuse with different payload.")
            return CandidatePublicApplyResponse.model_validate(existing.response_payload)

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
    response_payload = CandidatePublicApplyResponse(
        session_id=candidate_session.session_id,
        candidate_id=candidate_session.candidate_id,
        reply=(
            f"Hi there! 👋 I'm the Hiring Assistant for Talent Spark. You're applying for the position of "
            f"{candidate_session.job_title}. Question 1 of {len(candidate_session.questions)}: {first_question}"
        ),
        question_number=1,
        total_questions=len(candidate_session.questions),
    )
    if idempotency_key:
        try:
            save_record(
                session=session,
                idempotency_key=idempotency_key,
                endpoint="POST /api/candidates/apply/{job_id}",
                request_hash=payload_hash(request_payload),
                response_payload=response_payload.model_dump(),
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return response_payload


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
    idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
    session: Session = Depends(get_session),
) -> CandidatePublicSubmitResponse:
    request_payload = {"session_id": payload.session_id}
    if idempotency_key:
        request_digest = payload_hash(request_payload)
        existing = fetch_record(session=session, idempotency_key=idempotency_key)
        if existing:
            if existing.request_hash != request_digest:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key reuse with different payload.")
            return CandidatePublicSubmitResponse.model_validate(existing.response_payload)

    try:
        result = finalize_candidate_application(session=session, session_id=payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    response_payload = CandidatePublicSubmitResponse(
        reply=str(result["reply"]),
        submitted=bool(result["submitted"]),
    )
    if idempotency_key:
        try:
            save_record(
                session=session,
                idempotency_key=idempotency_key,
                endpoint="POST /api/candidates/submit",
                request_hash=payload_hash(request_payload),
                response_payload=response_payload.model_dump(),
            )
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return response_payload
