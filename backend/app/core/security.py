from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings

try:
    from passlib.context import CryptContext
except ModuleNotFoundError:  # pragma: no cover - local env may not have passlib installed
    CryptContext = None


# Use bcrypt_sha256 to safely support long passwords/tokens while remaining
# compatible with legacy bcrypt hashes.
pwd_context = (
    CryptContext(
        schemes=["bcrypt_sha256", "bcrypt"],
        deprecated="auto",
    )
    if CryptContext is not None
    else None
)


def _legacy_hash_password(password: str, *, salt: str | None = None) -> str:
    password_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), password_salt.encode("utf-8"), 100_000)
    return f"{password_salt}${digest.hex()}"


def hash_password(password: str, *, salt: str | None = None) -> str:
    if salt is not None:
        return _legacy_hash_password(password, salt=salt)
    if pwd_context is not None:
        return pwd_context.hash(password)
    return _legacy_hash_password(password)


def verify_password(password: str, hashed_password: str) -> bool:
    if pwd_context is not None and pwd_context.identify(hashed_password) is not None:
        try:
            return pwd_context.verify(password, hashed_password)
        except ValueError:
            # bcrypt raises for secrets >72 bytes; bcrypt_sha256 avoids this for
            # new hashes, and legacy bcrypt hashes should fail closed here.
            return False

    try:
        salt, expected_digest = hashed_password.split("$", 1)
    except ValueError:
        return False
    candidate = _legacy_hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, f"{salt}${expected_digest}")


def password_needs_rehash(hashed_password: str) -> bool:
    if pwd_context is None:
        return False
    identified_scheme = pwd_context.identify(hashed_password)
    if identified_scheme is None:
        return True
    return bool(pwd_context.needs_update(hashed_password))


def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.algorithm])


def read_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    if not authorization_header.lower().startswith("bearer "):
        return None
    return authorization_header.split(" ", 1)[1].strip()


def require_token(token: str | None) -> dict[str, Any]:
    if not token:
        raise JWTError("Missing bearer token.")
    return decode_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
