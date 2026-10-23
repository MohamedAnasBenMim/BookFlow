"""Configuration (variables d'environnement, préfixe BOOKFLOW_ facultatif)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://bookflow:bookflow@localhost:5432/bookflow"
    redis_url: str | None = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Render / Heroku fournissent postgres:// ou postgresql:// : on force le pilote psycopg 3
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    jwt_secret: str = "dev-secret-change-me-dev-secret-change-me"
    jwt_ttl_minutes: int = 60 * 12

    # URL publique du frontend (liens de paiement et emails) et origines CORS autorisées
    frontend_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"

    # Paiement : "fake" (démo et tests, aucun compte requis) ou "stripe" (mode test)
    payments_provider: str = "fake"
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    pending_payment_ttl_minutes: int = 15

    # Emails : "console" (logs) ou "smtp"
    email_backend: str = "console"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "BookFlow <no-reply@bookflow.dev>"
    reminder_hours_before: int = 24

    # Connexion Google (Google Identity Services, vérification du jeton côté serveur)
    google_client_id: str | None = None

    # Cache et limitation de débit
    slots_cache_ttl_seconds: int = 60
    rate_limit_bookings_per_minute: int = 10
    rate_limit_login_per_minute: int = 5

    slot_step_minutes: int = 15
    min_notice_minutes: int = 60
    max_days_ahead: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
