"""Authentification, Google, webhook Stripe, cache, limitation de débit, observabilité."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import cache, security
from app.config import get_settings

from .conftest import next_weekday
from .test_booking import book, slot_at


# ---------- comptes ----------
def test_register_login_me(client, owner):
    token = client.post("/auth/login", json={"email": "owner@alpha.dev", "password": "password123"}).json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["memberships"] == [{"tenant_slug": "alpha", "tenant_name": "Alpha", "role": "owner"}]


def test_register_conflicts_and_bad_login(client, owner):
    base = {"email": "owner@alpha.dev", "password": "password123", "name": "A", "business_name": "Other", "slug": "other"}
    assert client.post("/auth/register", json=base).status_code == 409
    assert client.post("/auth/register", json={**base, "email": "n@n.dev", "slug": "alpha"}).status_code == 409
    assert client.post("/auth/register", json={**base, "email": "n@n.dev", "slug": "Bad Slug!"}).status_code == 422
    assert client.post("/auth/login", json={"email": "owner@alpha.dev", "password": "wrong-pass"}).status_code == 401


def test_invalid_or_missing_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer abc"}).status_code == 401
    expired = jwt.encode({"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(minutes=1)}, get_settings().jwt_secret, "HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    ghost = security.create_token(uuid.uuid4())
    assert client.get("/me", headers={"Authorization": f"Bearer {ghost}"}).status_code == 401


# ---------- Google ----------
@pytest.fixture()
def google_key(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(security, "_google_jwks", lambda: FakeJWKS())
    monkeypatch.setattr(get_settings(), "google_client_id", "client-123")
    return key


def google_token(key, **over):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "client-123",
        "sub": "g-42",
        "email": "g@gmail.com",
        "email_verified": True,
        "name": "G User",
        "exp": int(time.time()) + 300,
        **over,
    }
    return jwt.encode(claims, key, "RS256")


def test_google_sign_in_creates_then_reuses_user(client, google_key):
    t1 = client.post("/auth/google", json={"id_token": google_token(google_key)})
    t2 = client.post("/auth/google", json={"id_token": google_token(google_key)})
    assert t1.status_code == t2.status_code == 200
    me1 = client.get("/me", headers={"Authorization": f"Bearer {t1.json()['access_token']}"}).json()
    me2 = client.get("/me", headers={"Authorization": f"Bearer {t2.json()['access_token']}"}).json()
    assert me1["id"] == me2["id"] and me1["email"] == "g@gmail.com"


def test_google_rejects_wrong_audience_and_unverified_email(client, google_key):
    assert client.post("/auth/google", json={"id_token": google_token(google_key, aud="other")}).status_code == 401
    assert client.post("/auth/google", json={"id_token": google_token(google_key, email_verified=False)}).status_code == 401


def test_google_disabled_without_client_id(client):
    assert client.post("/auth/google", json={"id_token": "x"}).status_code == 401


# ---------- Stripe ----------
def stripe_signature(payload: bytes, secret: str = "whsec_test_secret") -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def checkout_completed(event_id: str, booking_id: str, tenant_id: str) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {"id": "cs_test_1", "object": "checkout.session", "metadata": {"booking_id": booking_id, "tenant_id": tenant_id}}
            },
        }
    ).encode()


def test_stripe_webhook_confirms_once(client, owner):
    from sqlalchemy import select

    from app.db import global_session
    from app.models import Tenant

    created = book(client, owner["paid"]["id"], slot_at(next_weekday(2), 10)).json()
    with global_session() as db:
        tenant_id = str(db.scalar(select(Tenant.id).where(Tenant.slug == "alpha")))
    payload = checkout_completed("evt_1", created["booking"]["id"], tenant_id)
    r = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": stripe_signature(payload)})
    assert r.json() == {"confirmed": True}
    again = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": stripe_signature(payload)})
    assert again.json() == {"duplicate": "evt_1"}
    status = client.get(f"/public/alpha/bookings/{created['booking']['id']}", params={"token": created["access_token"]}).json()
    assert status["status"] == "confirmed"


def test_stripe_webhook_rejects_bad_signature_and_ignores_other_events(client):
    payload = json.dumps({"id": "evt_x", "object": "event", "type": "invoice.paid", "data": {"object": {}}}).encode()
    assert client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": "t=1,v1=bad"}).status_code == 400
    assert (
        client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": stripe_signature(payload, "whsec_other")}).status_code
        == 400
    )
    ok = client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": stripe_signature(payload)})
    assert ok.json() == {"ignored": "invoice.paid"}


def test_stripe_checkout_session_is_created_with_metadata(client, owner, monkeypatch):
    captured = {}

    class FakeSession:
        id, url = "cs_test_123", "https://checkout.stripe.com/c/pay/cs_test_123"

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeSession()

    monkeypatch.setattr(get_settings(), "payments_provider", "stripe")
    monkeypatch.setattr("stripe.checkout.Session.create", fake_create)
    created = book(client, owner["paid"]["id"], slot_at(next_weekday(3), 10)).json()
    assert created["checkout_url"] == FakeSession.url
    assert captured["metadata"]["booking_id"] == created["booking"]["id"]
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 5000
    fake_link = f"/payments/fake/alpha/{created['booking']['id']}?token={created['access_token']}"
    assert client.get(fake_link).status_code == 404  # paiement simulé désactivé en mode Stripe


# ---------- cache et limitation ----------
def test_slots_are_cached_and_invalidated(client, owner):
    day = next_weekday(1)
    params = {"service_id": owner["free"]["id"], "date": day.isoformat()}
    n = len(client.get("/public/alpha/slots", params=params).json()["slots"])
    keys = cache.client().keys("bf:slots:*")
    assert len(keys) == 1
    book(client, owner["free"]["id"], slot_at(day, 9))
    assert len(client.get("/public/alpha/slots", params=params).json()["slots"]) == n - 2  # 9h00 et 9h15 bloqués (30 min)


def test_rate_limit_returns_429(client, owner, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_login_per_minute", 3)
    codes = [client.post("/auth/login", json={"email": "x@x.dev", "password": "password123"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_in_memory_rate_limit_fallback(monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", None)
    monkeypatch.setattr(cache, "_client", None)
    assert all(cache.allow("k-test", 2) for _ in range(2)) and not cache.allow("k-test", 2)
    assert cache.get_slots(uuid.uuid4(), "x") is None


def test_health_and_metrics(client, owner):
    assert client.get("/health").json()["status"] == "ok"
    client.get("/public/alpha")
    m = client.get("/metrics").text
    assert 'route="/public/{slug}"' in m


def test_password_hashing():
    h = security.hash_password("s3cret-pass")
    assert security.verify_password("s3cret-pass", h) and not security.verify_password("nope", h)
    assert not security.verify_password("x", None)
