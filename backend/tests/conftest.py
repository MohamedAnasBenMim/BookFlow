"""Tests sur une vraie base PostgreSQL (RLS, contrainte d'exclusion) et un vrai Redis.

Variables : TEST_DATABASE_URL (défaut : base bookflow_test locale), REDIS_URL.
Le rôle de connexion ne doit PAS être superutilisateur, sinon PostgreSQL ignore le RLS.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://bookflow:bookflow@localhost:5432/bookflow_test"))
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["EMAIL_BACKEND"] = "memory"
os.environ["PAYMENTS_PROVIDER"] = "fake"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret"
os.environ["RATE_LIMIT_BOOKINGS_PER_MINUTE"] = "1000"
os.environ["RATE_LIMIT_LOGIN_PER_MINUTE"] = "1000"

from datetime import UTC, date, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import cache, notify  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

TABLES = "processed_events, notifications, bookings, availability_rules, services, memberships, users, tenants"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    with engine.begin() as conn:
        is_super = conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
    assert not is_super, "les tests doivent tourner avec un rôle non superutilisateur (le RLS serait ignoré)"
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean():
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    r = cache.client()
    if r is not None:
        r.flushdb()
    notify.OUTBOX.clear()
    cache._tenants.clear()  # les tenants sont recréés à chaque test avec de nouveaux identifiants
    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def next_weekday(weekday: int, min_days: int = 2) -> date:
    d = datetime.now(UTC).date() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


@pytest.fixture()
def owner(client):
    """Entreprise « alpha » créée par l'API d'inscription (lun-ven 9h-18h), avec une prestation payante et une gratuite."""
    r = client.post(
        "/auth/register",
        json={
            "email": "owner@alpha.dev",
            "password": "password123",
            "name": "Alice",
            "business_name": "Alpha",
            "slug": "alpha",
            "timezone": "Europe/Paris",
        },
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Tenant": "alpha"}
    paid = client.post("/admin/services", headers=h, json={"name": "Consultation", "duration_minutes": 60, "price_cents": 5000}).json()
    free = client.post("/admin/services", headers=h, json={"name": "Appel", "duration_minutes": 30, "price_cents": 0}).json()
    return {"headers": h, "paid": paid, "free": free}


@pytest.fixture()
def settings():
    return get_settings()
