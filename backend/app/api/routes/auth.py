from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.app.core.config import settings
from backend.app.core.database import get_session
from backend.app.core.security import create_access_token, hash_password, password_needs_rehash, verify_password
from backend.app.deps import get_current_user, require_roles
from backend.app.models import Employee, User, UserRole
from backend.app.schemas import (
    AdminUserRead,
    LoginRequest,
    PromoteCandidateRequest,
    SignupRequest,
    TokenResponse,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(payload.password)
        session.add(user)
        session.commit()
        session.refresh(user)

    access_token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, session: Session = Depends(get_session)) -> TokenResponse:
    existing = session.exec(select(User).where(User.email == payload.email)).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=UserRole.CANDIDATE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    access_token = create_access_token(
        subject=str(user.id),
        role=user.role.value,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserProfile)
def me(current_user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile.model_validate(current_user)


@router.get("/users", response_model=list[AdminUserRead])
def list_users(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[AdminUserRead]:
    users = session.exec(select(User).order_by(User.created_at.asc())).all()
    return [AdminUserRead.model_validate(user) for user in users]


@router.post("/users/{user_id}/promote", response_model=AdminUserRead)
def promote_candidate_to_employee(
    user_id: int,
    payload: PromoteCandidateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> AdminUserRead:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.role != UserRole.CANDIDATE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only candidate users can be promoted.")

    employee = Employee(
        name=user.full_name,
        department=payload.department,
        annual_allowance=payload.annual_allowance,
        leave_balance=payload.annual_allowance,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)

    user.role = UserRole.EMPLOYEE
    user.employee_id = employee.id
    session.add(user)
    session.commit()
    session.refresh(user)
    return AdminUserRead.model_validate(user)
