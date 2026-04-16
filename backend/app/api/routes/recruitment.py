from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select

from app.core.database import get_session
from app.deps import require_roles
from app.models import Candidate, CandidateStatus, Job, JobStatus, User, UserRole
from app.schemas import (
    CandidateApplicationRequest,
    CandidateApplicationStatusResponse,
    CandidateInterviewResponse,
    CandidateRead,
    CandidateScoreResponse,
    InterviewAnswerRequest,
    PublicJobRead,
)
from app.services.admin_dashboard import split_full_name
from app.services.recruitment import (
    build_candidate_interview_payload,
    get_current_question,
    hydrate_legacy_candidate,
    initialize_candidate_interview,
    normalize_screening_answers,
    parse_resume_file,
    submit_interview_answer,
)

router = APIRouter(prefix="/recruitment", tags=["recruitment"])


@router.get("/jobs", response_model=list[PublicJobRead])
def list_open_jobs(session: Session = Depends(get_session)) -> list[PublicJobRead]:
    jobs = session.exec(
        select(Job).where(Job.status == JobStatus.OPEN).order_by(Job.created_at.desc())
    ).all()
    return [PublicJobRead.model_validate(job) for job in jobs]


@router.get("/candidates", response_model=list[CandidateRead])
def list_candidates(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[CandidateRead]:
    candidates = session.exec(select(Candidate).order_by(Candidate.ai_score.desc())).all()
    changed = False
    for candidate in candidates:
        candidate_changed = hydrate_legacy_candidate(candidate)
        changed = candidate_changed or changed
        if candidate_changed:
            session.add(candidate)
    if changed:
        session.commit()
        for candidate in candidates:
            session.refresh(candidate)
    return [CandidateRead.model_validate(candidate) for candidate in candidates]


@router.get("/status", response_model=CandidateApplicationStatusResponse)
def my_candidate_status(
    current_user: User = Depends(require_roles(UserRole.CANDIDATE)),
    session: Session = Depends(get_session),
) -> CandidateApplicationStatusResponse:
    candidate = session.get(Candidate, current_user.candidate_id) if current_user.candidate_id else None
    if candidate is None:
        return CandidateApplicationStatusResponse(candidate=None)
    if hydrate_legacy_candidate(candidate):
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
    return CandidateApplicationStatusResponse(candidate=CandidateRead.model_validate(candidate))


@router.post("/apply", response_model=CandidateApplicationStatusResponse)
def apply_for_job(
    payload: CandidateApplicationRequest,
    current_user: User = Depends(require_roles(UserRole.CANDIDATE)),
    session: Session = Depends(get_session),
) -> CandidateApplicationStatusResponse:
    selected_job = session.get(Job, payload.job_id) if payload.job_id is not None else None
    if payload.job_id is not None and selected_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected job not found.")

    role_title = selected_job.title if selected_job is not None else (payload.role_title or "").strip()
    job_description = selected_job.description if selected_job is not None else (payload.job_description or "").strip()
    if not role_title or not job_description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either a valid job_id or both role_title and job_description are required.",
        )

    first_name, last_name = split_full_name(current_user.full_name)
    candidate = session.get(Candidate, current_user.candidate_id) if current_user.candidate_id else None
    if candidate is None:
        candidate = session.exec(select(Candidate).where(Candidate.email == current_user.email)).first()

    if candidate is None:
        candidate = Candidate(
            first_name=first_name,
            last_name=last_name,
            name=current_user.full_name,
            email=current_user.email,
            job_id=selected_job.job_id if selected_job is not None else None,
            role_title=role_title,
            resume_text="",
            job_description=job_description,
            cv_summary="Application submitted. CV summary will appear after resume screening.",
            status=CandidateStatus.UNDER_REVIEW,
            summary="Application submitted. Resume screening and recruiter review are pending.",
        )
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        candidate.name = current_user.full_name
        candidate.email = current_user.email
        candidate.job_id = selected_job.job_id if selected_job is not None else candidate.job_id
        candidate.role_title = role_title
        candidate.job_description = job_description
        if not candidate.cv_summary:
            candidate.cv_summary = "Application submitted. CV summary will appear after resume screening."
        if not candidate.summary:
            candidate.summary = "Application submitted. Resume screening and recruiter review are pending."
        if candidate.status == CandidateStatus.REJECTED:
            candidate.status = CandidateStatus.UNDER_REVIEW

    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    if current_user.candidate_id != candidate.id:
        current_user.candidate_id = candidate.id
        session.add(current_user)
        session.commit()
        session.refresh(current_user)

    return CandidateApplicationStatusResponse(candidate=CandidateRead.model_validate(candidate))


@router.post("/score-resume", response_model=CandidateScoreResponse)
def score_resume_endpoint(
    candidate_name: str = Form(...),
    email: str = Form(...),
    role_title: str = Form(...),
    job_description: str = Form(...),
    screening_answers: str | None = Form(default=None),
    resume: UploadFile = File(...),
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> CandidateScoreResponse:
    resume_text = parse_resume_file(resume)
    first_name, last_name = split_full_name(candidate_name)
    matching_job = session.exec(select(Job).where(Job.title == role_title)).first()
    candidate = session.exec(select(Candidate).where(Candidate.email == email)).first()
    if candidate is None:
        candidate = Candidate(
            first_name=first_name,
            last_name=last_name,
            name=candidate_name,
            email=email,
            job_id=matching_job.job_id if matching_job is not None else None,
            role_title=role_title,
            resume_text=resume_text,
            job_description=job_description,
            status=CandidateStatus.UNDER_REVIEW,
        )
    else:
        candidate.first_name = first_name
        candidate.last_name = last_name
        if matching_job is not None:
            candidate.job_id = matching_job.job_id
    scoring = initialize_candidate_interview(
        candidate,
        candidate_name=candidate_name,
        role_title=role_title,
        resume_text=resume_text,
        job_description=job_description,
        screening_answers=normalize_screening_answers(screening_answers),
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)

    return CandidateScoreResponse(
        candidate=CandidateRead.model_validate(candidate),
        scorecard=scoring["scorecard"],
        resume_excerpt=resume_text[:500],
    )


@router.post("/candidates/{candidate_id}/interview/answer", response_model=CandidateInterviewResponse)
def submit_candidate_interview_answer(
    candidate_id: int,
    payload: InterviewAnswerRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> CandidateInterviewResponse:
    candidate = session.exec(select(Candidate).where(Candidate.id == candidate_id)).first()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")
    if hydrate_legacy_candidate(candidate):
        session.add(candidate)
        session.commit()
        session.refresh(candidate)

    current_question = get_current_question(candidate)
    if current_question is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interview already completed for this candidate.",
        )

    evaluation = submit_interview_answer(candidate, payload.answer)
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    interview_payload = build_candidate_interview_payload(candidate)
    return CandidateInterviewResponse(
        candidate=CandidateRead.model_validate(candidate),
        evaluation=evaluation,
        next_question=interview_payload["next_question"],
    )
