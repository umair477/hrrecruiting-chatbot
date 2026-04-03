from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.deps import require_roles
from backend.app.models import Candidate, CandidateStatus, User, UserRole
from backend.app.schemas import (
    CandidateApplicationRequest,
    CandidateApplicationStatusResponse,
    CandidateInterviewResponse,
    CandidateRead,
    CandidateScoreResponse,
    InterviewAnswerRequest,
)
from backend.app.services.recruitment import (
    build_candidate_interview_payload,
    get_current_question,
    hydrate_legacy_candidate,
    initialize_candidate_interview,
    normalize_screening_answers,
    parse_resume_file,
    submit_interview_answer,
)

router = APIRouter(prefix="/recruitment", tags=["recruitment"])


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
    candidate = session.get(Candidate, current_user.candidate_id) if current_user.candidate_id else None
    if candidate is None:
        candidate = session.exec(select(Candidate).where(Candidate.email == current_user.email)).first()

    if candidate is None:
        candidate = Candidate(
            name=current_user.full_name,
            email=current_user.email,
            role_title=payload.role_title,
            resume_text="",
            job_description=payload.job_description,
            status=CandidateStatus.UNDER_REVIEW,
            summary="Application submitted. Resume screening and recruiter review are pending.",
        )
    else:
        candidate.name = current_user.full_name
        candidate.email = current_user.email
        candidate.role_title = payload.role_title
        candidate.job_description = payload.job_description
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
    candidate = session.exec(select(Candidate).where(Candidate.email == email)).first()
    if candidate is None:
        candidate = Candidate(
            name=candidate_name,
            email=email,
            role_title=role_title,
            resume_text=resume_text,
            job_description=job_description,
            status=CandidateStatus.UNDER_REVIEW,
        )
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
