from __future__ import annotations

from dataclasses import dataclass
import os


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


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
    signup_url: str = os.getenv("SIGNUP_URL", "http://localhost:5173/employee/signup")
    openai_email_model: str = os.getenv("OPENAI_EMAIL_MODEL", "gpt-4o-mini-2024-07-18")


settings = Settings()
