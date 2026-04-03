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
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_signing_secret: str = os.getenv("SLACK_SIGNING_SECRET", "")
    teams_app_id: str = os.getenv("TEAMS_APP_ID", "")
    teams_app_password: str = os.getenv("TEAMS_APP_PASSWORD", "")


settings = Settings()
