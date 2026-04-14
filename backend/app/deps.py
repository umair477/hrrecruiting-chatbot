from __future__ import annotations

from typing import Callable

from fastapi import Cookie, Depends, Header, HTTPException, status
from jose import JWTError
from sqlmodel import Session, select

from backend.app.core.database import get_session
from backend.app.core.config import settings
from backend.app.core.security import hash_token, read_bearer_token, require_token
from backend.app.models import TokenBlocklist, User, UserRole


def get_current_token(
    authorization: str | None = Header(default=None),
    employee_auth_cookie: str | None = Cookie(default=None, alias=settings.employee_auth_cookie_name),
) -> str | None:
    return read_bearer_token(authorization) or employee_auth_cookie


def _ensure_token_not_blocked(token: str, session: Session) -> None:
    token_digest = hash_token(token)
    blocked = session.exec(select(TokenBlocklist).where(TokenBlocklist.token_hash == token_digest)).first()
    if blocked is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired or been logged out.")


def get_current_user(
    token: str | None = Depends(get_current_token),
    session: Session = Depends(get_session),
) -> User:
    try:
        if token is None:
            raise JWTError("Missing bearer token.")
        _ensure_token_not_blocked(token, session)
        payload = require_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token.") from exc

    user = session.exec(select(User).where(User.id == user_id)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")
        return current_user

    return _dependency
