from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import JWTError
from sqlmodel import Session, select

from backend.app.core.config import settings
from backend.app.core.database import get_session
from backend.app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)
from backend.app.deps import get_current_token, get_current_user, require_roles
from backend.app.models import Employee, TokenBlocklist, User, UserRole
from backend.app.schemas import (
    AdminUserRead,
    EmployeeAuthProfile,
    EmployeeAuthResponse,
    EmployeeLoginRequest,
    EmployeeLogoutResponse,
    EmployeeSignupRequest,
    EmployeeSignupResponse,
    LoginRequest,
    PromoteCandidateRequest,
    SignupRequest,
    TokenResponse,
    UserProfile,
)

router = APIRouter(prefix="/auth", tags=["auth"])

PASSWORD_STRENGTH_PATTERN = re.compile(r"^(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _set_employee_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.employee_auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.employee_auth_cookie_secure,
        samesite=settings.employee_auth_cookie_samesite,
        max_age=settings.employee_token_expire_hours * 60 * 60,
        expires=settings.employee_token_expire_hours * 60 * 60,
        path="/",
    )


def _clear_employee_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.employee_auth_cookie_name,
        httponly=True,
        secure=settings.employee_auth_cookie_secure,
        samesite=settings.employee_auth_cookie_samesite,
        path="/",
    )


def _employee_profile(employee: Employee) -> EmployeeAuthProfile:
    return EmployeeAuthProfile(
        employee_id=int(employee.id),
        full_name=employee.full_name or employee.name,
        email=employee.official_email,
        department=employee.department,
        designation=employee.designation,
        date_of_joining=employee.date_of_joining,
        role="EMPLOYEE",
        is_active=employee.is_active,
    )


def _ensure_password_strength(password: str) -> None:
    if not PASSWORD_STRENGTH_PATTERN.match(password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long and include 1 uppercase letter, 1 number, and 1 special character.",
        )


def _get_employee_by_email(session: Session, email: str) -> Employee | None:
    normalized_email = _normalize_email(email)
    employees = session.exec(select(Employee)).all()
    for employee in employees:
        if _normalize_email(employee.official_email) == normalized_email:
            return employee
    return None


def _ensure_employee_user(session: Session, employee: Employee) -> User:
    email = _normalize_email(employee.official_email)
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            full_name=employee.full_name or employee.name,
            hashed_password=employee.password_hash or "",
            role=UserRole.EMPLOYEE,
            employee_id=employee.id,
        )
    elif user.role != UserRole.EMPLOYEE and user.employee_id != employee.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already linked to a different account.",
        )
    else:
        user.full_name = employee.full_name or employee.name
        user.role = UserRole.EMPLOYEE
        user.employee_id = employee.id
        if employee.password_hash:
            user.hashed_password = employee.password_hash

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _record_failed_login(session: Session, employee: Employee) -> None:
    employee.failed_login_attempts += 1
    if employee.failed_login_attempts >= settings.employee_login_max_attempts:
        employee.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.employee_login_lock_minutes)
        employee.failed_login_attempts = 0
    session.add(employee)
    session.commit()


def _reset_login_attempts(session: Session, employee: Employee) -> None:
    employee.failed_login_attempts = 0
    employee.locked_until = None
    employee.last_login_at = datetime.now(timezone.utc)
    session.add(employee)
    session.commit()


def _ensure_employee_can_authenticate(employee: Employee) -> None:
    if not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your employee account is inactive. Please contact HR.",
        )
    if employee.locked_until and employee.locked_until > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes.",
        )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = session.exec(select(User).where(User.email == _normalize_email(payload.email))).first()
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
    normalized_email = _normalize_email(payload.email)
    existing = session.exec(select(User).where(User.email == normalized_email)).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered.")

    user = User(
        email=normalized_email,
        full_name=payload.full_name.strip(),
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


@router.post("/employee/signup", response_model=EmployeeSignupResponse, status_code=status.HTTP_201_CREATED)
def employee_signup(payload: EmployeeSignupRequest, session: Session = Depends(get_session)) -> EmployeeSignupResponse:
    normalized_email = _normalize_email(payload.email)
    employee = _get_employee_by_email(session, normalized_email)
    if employee is None or not employee.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not registered as an employee. Please contact HR.",
        )

    if (employee.full_name or employee.name).strip().lower() != payload.full_name.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Full name does not match the employee record on file.",
        )
    if payload.password != payload.confirm_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password and confirm password must match.")
    _ensure_password_strength(payload.password)
    if employee.password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This employee account has already been activated. Please log in instead.",
        )

    employee.full_name = payload.full_name.strip()
    employee.name = payload.full_name.strip()
    employee.official_email = normalized_email
    employee.password_hash = hash_password(payload.password)
    employee.failed_login_attempts = 0
    employee.locked_until = None
    session.add(employee)
    session.commit()
    session.refresh(employee)

    _ensure_employee_user(session, employee)
    return EmployeeSignupResponse(message="Account created successfully. You can now log in.")


@router.post("/employee/login", response_model=EmployeeAuthResponse)
def employee_login(
    payload: EmployeeLoginRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> EmployeeAuthResponse:
    normalized_email = _normalize_email(payload.email)
    employee = _get_employee_by_email(session, normalized_email)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    _ensure_employee_can_authenticate(employee)
    if not employee.password_hash or not verify_password(payload.password, employee.password_hash):
        _record_failed_login(session, employee)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    if password_needs_rehash(employee.password_hash):
        employee.password_hash = hash_password(payload.password)
        session.add(employee)
        session.commit()
        session.refresh(employee)

    user = _ensure_employee_user(session, employee)
    _reset_login_attempts(session, employee)

    access_token = create_access_token(
        subject=str(user.id),
        role="employee",
        expires_delta=timedelta(hours=settings.employee_token_expire_hours),
        extra_claims={
            "employee_id": employee.id,
            "full_name": employee.full_name or employee.name,
            "email": employee.official_email,
        },
    )
    _set_employee_auth_cookie(response, access_token)
    return EmployeeAuthResponse(
        access_token=access_token,
        employee=_employee_profile(employee),
    )


@router.get("/employee/me", response_model=EmployeeAuthProfile)
def employee_me(
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> EmployeeAuthProfile:
    if current_user.employee_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee profile not linked to this user.")
    employee = session.get(Employee, current_user.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")
    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Employee account is inactive.")
    return _employee_profile(employee)


@router.post("/employee/logout", response_model=EmployeeLogoutResponse)
def employee_logout(
    response: Response,
    token: str | None = Depends(get_current_token),
    current_user: User = Depends(require_roles(UserRole.EMPLOYEE)),
    session: Session = Depends(get_session),
) -> EmployeeLogoutResponse:
    if token:
        try:
            payload = decode_token(token)
            expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
        except (JWTError, KeyError, TypeError, ValueError):
            expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.employee_token_expire_hours)

        blocked = TokenBlocklist(
            token_hash=hash_token(token),
            user_id=current_user.id,
            employee_id=current_user.employee_id,
            expires_at=expires_at,
        )
        session.add(blocked)
        session.commit()

    _clear_employee_auth_cookie(response)
    return EmployeeLogoutResponse(message="Logged out successfully.")


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
        full_name=user.full_name,
        official_email=_normalize_email(user.email),
        department=payload.department,
        designation="Employee",
        date_of_joining=datetime.now(timezone.utc).date(),
        is_active=True,
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
