"""Application settings.

Every value is environment-driven so that no deployment concern is baked into
code. Business preferences (roles, salary, keywords, schedules) deliberately do
NOT live here -- they are user data and belong in the database.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root: backend/app/core/config.py -> backend/app/core -> ... -> root
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core ---
    app_name: str = "AI Job Application Agent"
    app_version: str = "2.0.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    app_secret_key: str = "dev-only-insecure-secret-change-me"

    # --- database ---
    database_url: str = "sqlite+pysqlite:///./data/jobagent.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- auth ---
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    # "none" when the web app and API are on different sites (e.g. two
    # *.onrender.com hosts), otherwise the browser never sends the refresh cookie.
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    bootstrap_email: str = ""
    bootstrap_password: str = ""

    # --- web ---
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    data_dir: str = str(ROOT_DIR / "data")
    max_upload_bytes: int = 10 * 1024 * 1024
    rate_limit_per_minute: int = 120

    # --- ai ---
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_cheap_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 60.0
    openai_max_retries: int = 2
    ai_monthly_budget_usd: float = 25.0

    # --- job sources ---
    job_search_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    remotive_enabled: bool = True

    # --- notifications ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    telegram_bot_token: str = ""
    slack_webhook_url: str = ""
    whatsapp_provider: str = ""
    whatsapp_api_key: str = ""

    # --- scheduler ---
    scheduler_enabled: bool = True
    timezone: str = "Asia/Kolkata"

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment in ("production", "staging")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def upload_dir(self) -> Path:
        p = Path(self.data_dir).expanduser()
        if not p.is_absolute():
            p = (ROOT_DIR / p).resolve()
        return p / "uploads"

    def resolved_database_url(self) -> str:
        """Make relative SQLite paths absolute so the CWD cannot change the DB.

        Hosted Postgres (Render, Heroku, ...) hands out ``postgres://`` or
        ``postgresql://`` URLs, which SQLAlchemy maps to psycopg2; this app
        ships psycopg 3, so the driver is pinned explicitly.
        """
        url = self.database_url
        for scheme in ("postgres://", "postgresql://"):
            if url.startswith(scheme):
                return "postgresql+psycopg://" + url[len(scheme):]
        prefix = "sqlite+pysqlite:///./"
        if url.startswith(prefix):
            rel = url[len(prefix):]
            target = (ROOT_DIR / rel).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite+pysqlite:///{target.as_posix()}"
        return url

    def validate_for_production(self) -> list[str]:
        """Return a list of blocking problems for a production boot."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.app_secret_key == "dev-only-insecure-secret-change-me" or len(self.app_secret_key) < 32:
            problems.append("APP_SECRET_KEY must be set to a unique value of at least 32 characters.")
        if self.is_sqlite:
            problems.append("DATABASE_URL must point at PostgreSQL in production, not SQLite.")
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS must not be a wildcard in production.")
        if any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
               for o in self.cors_origin_list):
            problems.append("CORS_ORIGINS must use HTTPS for non-local origins in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
