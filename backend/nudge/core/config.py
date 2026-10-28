from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Nudge AI"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    database_url: str = "postgresql+psycopg://nudge:nudge@localhost:5432/nudge"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-change-me-please-use-a-long-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    reminder_eval_interval_seconds: int = 300

    email_provider: str = "console"  # console | smtp
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "nudge@localhost"

    reminder_weights_version: str = "v1"
    reminder_send_threshold: float = 0.75
    reminder_digest_threshold: float = 0.45
    reminder_daily_cap: int = 12

    # LLM — OpenAI is the Phase 2 default; stub used when key unset or LLM_PROVIDER=stub
    llm_provider: str = "openai"  # openai | stub | anthropic (stubbed)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    llm_timeout_seconds: float = 45.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
