from __future__ import annotations

from dataclasses import dataclass
import os


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_url(value: str) -> str:
    return value.strip().rstrip("/")


def _is_local_url(value: str) -> bool:
    lowered = value.lower()
    return (
        "localhost" in lowered
        or "127.0.0.1" in lowered
        or "0.0.0.0" in lowered
        or "::1" in lowered
    )


def _is_production_runtime() -> bool:
    env = os.getenv("ENV", "").strip().lower()
    app_env = os.getenv("APP_ENV", "").strip().lower()
    render = os.getenv("RENDER", "").strip().lower() == "true"
    return render or env in {"production", "prod"} or app_env in {"production", "prod"}


def _resolve_frontend_base_url() -> str:
    explicit = _normalize_url(os.getenv("FRONTEND_BASE_URL", ""))
    if explicit and (not _is_local_url(explicit) or not _is_production_runtime()):
        return explicit

    allowed = _split_csv(os.getenv("ALLOWED_ORIGINS", ""))
    for origin in allowed:
        normalized = _normalize_url(origin)
        if normalized and not _is_local_url(normalized):
            return normalized

    vercel_candidate = _normalize_url(
        os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "") or os.getenv("VERCEL_URL", "")
    )
    if vercel_candidate:
        if vercel_candidate.startswith("http://") or vercel_candidate.startswith("https://"):
            return vercel_candidate
        return f"https://{vercel_candidate}"

    return explicit or "http://localhost:5173"


_RESOLVED_FRONTEND_BASE_URL = _resolve_frontend_base_url()


def _resolve_signup_url() -> str:
    explicit = _normalize_url(os.getenv("SIGNUP_URL", ""))
    if explicit and (not _is_local_url(explicit) or not _is_production_runtime()):
        return explicit
    return f"{_RESOLVED_FRONTEND_BASE_URL}/employee/signup"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Talent Spark HR Backend"
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./talent_spark.db",
    )
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "development-secret")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))
    algorithm: str = "HS256"
    allowed_origins: list[str] = tuple(
        _split_csv(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8080"))
    )
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_evaluator_model: str = os.getenv("OPENAI_EVALUATOR_MODEL", "gpt-5-mini")
    openai_recruitment_model: str = os.getenv("OPENAI_RECRUITMENT_MODEL", "gpt-5-mini")
    openai_leave_chat_model: str = os.getenv("OPENAI_LEAVE_CHAT_MODEL", "gpt-5-mini")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    teams_app_id: str = os.getenv("TEAMS_APP_ID", "")
    teams_app_password: str = os.getenv("TEAMS_APP_PASSWORD", "")
    employee_auth_cookie_name: str = os.getenv("EMPLOYEE_AUTH_COOKIE_NAME", "employee_access_token")
    employee_auth_cookie_secure: bool = os.getenv("EMPLOYEE_AUTH_COOKIE_SECURE", "false").lower() == "true"
    employee_auth_cookie_samesite: str = os.getenv("EMPLOYEE_AUTH_COOKIE_SAMESITE", "lax")
    employee_token_expire_hours: int = int(os.getenv("EMPLOYEE_TOKEN_EXPIRE_HOURS", "24"))
    employee_login_max_attempts: int = int(os.getenv("EMPLOYEE_LOGIN_MAX_ATTEMPTS", "5"))
    employee_login_lock_minutes: int = int(os.getenv("EMPLOYEE_LOGIN_LOCK_MINUTES", "15"))
    email_from_address: str = os.getenv("EMAIL_FROM_ADDRESS", "hr@company.com")
    email_from_name: str = os.getenv("EMAIL_FROM_NAME", "HR Team")
    sendgrid_api_key: str = os.getenv("SENDGRID_API_KEY", "")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    company_name: str = os.getenv("COMPANY_NAME", "Talent Spark")
    signup_url: str = _resolve_signup_url()
    openai_email_model: str = os.getenv("OPENAI_EMAIL_MODEL", "gpt-4o-mini-2024-07-18")
    frontend_base_url: str = _RESOLVED_FRONTEND_BASE_URL
    calendar_provider: str = os.getenv("CALENDAR_PROVIDER", "google")
    interview_duration_minutes: int = int(os.getenv("INTERVIEW_DURATION_MINUTES", "45"))
    working_hours_start: str = os.getenv("WORKING_HOURS_START", "09:00")
    working_hours_end: str = os.getenv("WORKING_HOURS_END", "17:00")
    slots_to_propose: int = int(os.getenv("SLOTS_TO_PROPOSE", "5"))
    booking_token_expiry_hours: int = int(os.getenv("BOOKING_TOKEN_EXPIRY_HOURS", "48"))
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "")
    google_calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    google_refresh_token: str = os.getenv("GOOGLE_REFRESH_TOKEN", "")


settings = Settings()
