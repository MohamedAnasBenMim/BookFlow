"""Isolation multi-tenant, rôles, tableau de bord."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text

from app.db import SessionLocal, set_context, tenant_session
from app.models import Booking, Service, Tenant

from .conftest import next_weekday
from .test_booking import book, slot_at


def register(client, email, slug):
    r = client.post(
        "/auth/register", json={"email": email, "password": "password123", "name": "X", "business_name": slug.title(), "slug": slug}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Tenant": slug}


def test_rls_blocks_cross_tenant_reads_even_without_where_clause(client, owner):
    register(client, "beta@beta.dev", "beta")
    with SessionLocal() as db, db.begin():
        set_context(db)
        alpha_id = db.scalar(select(Tenant.id).where(Tenant.slug == "alpha"))
        beta_id = db.scalar(select(Tenant.id).where(Tenant.slug == "beta"))
    with tenant_session(beta_id) as db:
        assert db.scalar(select(func.count()).select_from(Service)) == 0  # aucune ligne d'alpha visible
    with tenant_session(alpha_id) as db:
        assert db.scalar(select(func.count()).select_from(Service)) == 2
    with SessionLocal() as db, db.begin():  # sans contexte : rien n'est visible (échec fermé)
        assert db.scalar(text("SELECT count(*) FROM services")) == 0


def test_rls_blocks_cross_tenant_writes(client, owner):
    register(client, "beta@beta.dev", "beta")
    with SessionLocal() as db, db.begin():
        set_context(db)
        alpha_id = db.scalar(select(Tenant.id).where(Tenant.slug == "alpha"))
        beta_id = db.scalar(select(Tenant.id).where(Tenant.slug == "beta"))
    import pytest
    from sqlalchemy.exc import ProgrammingError

    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_session(beta_id) as db:
            db.add(Service(tenant_id=alpha_id, name="intrus", duration_minutes=30, price_cents=0))
            db.flush()


def test_cannot_administer_another_tenant(client, owner):
    beta = register(client, "beta@beta.dev", "beta")
    hijack = {**beta, "X-Tenant": "alpha"}
    assert client.get("/admin/services", headers=hijack).status_code == 403
    assert client.patch(f"/admin/services/{owner['paid']['id']}", headers=beta, json={"price_cents": 1}).status_code == 404


def test_public_booking_cannot_use_other_tenant_service(client, owner):
    register(client, "beta@beta.dev", "beta")
    r = client.post(
        "/public/beta/bookings",
        json={"service_id": owner["free"]["id"], "start": slot_at(next_weekday(1), 10), "customer_name": "x", "customer_email": "x@x.dev"},
    )
    assert r.status_code == 404


def test_staff_role_sees_only_own_bookings_and_cannot_manage(client, owner):
    h = owner["headers"]
    staff = client.post("/admin/staff", headers=h, json={"email": "bob@alpha.dev", "name": "Bob", "password": "password123"}).json()
    client.put(
        "/admin/availability",
        headers=h,
        params={"staff_id": staff["user_id"]},
        json=[{"weekday": d, "start_time": "09:00", "end_time": "18:00"} for d in range(5)],
    )
    day = next_weekday(2, min_days=9)
    book(client, owner["free"]["id"], slot_at(day, 9))
    book(client, owner["free"]["id"], slot_at(day, 9), "b@t.dev")
    token = client.post("/auth/login", json={"email": "bob@alpha.dev", "password": "password123"}).json()["access_token"]
    bob = {"Authorization": f"Bearer {token}", "X-Tenant": "alpha"}
    items = client.get("/admin/bookings", headers=bob).json()["items"]
    assert len(items) == 1 and items[0]["staff_id"] == staff["user_id"]
    assert len(client.get("/admin/bookings", headers=h).json()["items"]) == 2
    assert client.post("/admin/services", headers=bob, json={"name": "x", "duration_minutes": 30, "price_cents": 0}).status_code == 403
    assert client.get("/admin/stats", headers=bob).status_code == 403


def test_bookings_keyset_pagination(client, owner):
    day = next_weekday(1, min_days=9)
    for i in range(5):
        assert book(client, owner["free"]["id"], slot_at(day, 9 + i), f"p{i}@t.dev").status_code == 201
    seen, cursor = [], None
    while True:
        page = client.get("/admin/bookings", headers=owner["headers"], params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [b["start_at"] for b in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 5 and seen == sorted(seen)
    assert client.get("/admin/bookings", headers=owner["headers"], params={"cursor": "%%%"}).status_code == 400


def test_service_crud_and_archive(client, owner):
    h = owner["headers"]
    sid = owner["paid"]["id"]
    assert client.patch(f"/admin/services/{sid}", headers=h, json={"price_cents": 6000}).json()["price_cents"] == 6000
    assert client.delete(f"/admin/services/{sid}", headers=h).status_code == 204
    assert sid not in [s["id"] for s in client.get("/public/alpha").json()["services"]]
    assert client.get("/public/alpha/slots", params={"service_id": sid, "date": next_weekday(1).isoformat()}).status_code == 404
    assert client.delete(f"/admin/services/{uuid.uuid4()}", headers=h).status_code == 404
    assert client.patch(f"/admin/services/{uuid.uuid4()}", headers=h, json={"price_cents": 1}).status_code == 404


def test_admin_cancel_and_stats(client, owner):
    h = owner["headers"]
    day = next_weekday(1, min_days=2)
    a = book(client, owner["free"]["id"], slot_at(day, 9)).json()["booking"]["id"]
    book(client, owner["free"]["id"], slot_at(day, 10), "b@t.dev")
    assert client.post(f"/admin/bookings/{a}/cancel", headers=h).json()["status"] == "cancelled"
    assert client.post(f"/admin/bookings/{uuid.uuid4()}/cancel", headers=h).status_code == 404
    stats = client.get("/admin/stats", headers=h).json()
    assert stats["cancellation_rate_last_30_days"] == 0.5
    assert client.get("/admin/bookings", headers=h, params={"status": "cancelled"}).json()["items"][0]["id"] == a


def test_staff_management_rules(client, owner):
    h = owner["headers"]
    body = {"email": "c@alpha.dev", "name": "C", "password": "password123"}
    assert client.post("/admin/staff", headers=h, json=body).status_code == 201
    assert client.post("/admin/staff", headers=h, json=body).status_code == 409
    assert client.post("/admin/staff", headers=h, json={**body, "email": "d@alpha.dev", "role": "owner"}).status_code == 422
    assert len(client.get("/admin/staff", headers=h).json()) == 2
    assert client.put("/admin/availability", headers=h, params={"staff_id": str(uuid.uuid4())}, json=[]).status_code == 404
    bad = [{"weekday": 0, "start_time": "18:00", "end_time": "09:00"}]
    assert client.put("/admin/availability", headers=h, json=bad).status_code == 422
    assert len(client.get("/admin/availability", headers=h).json()) == 5


def test_bookings_survive_in_db_with_tenant_id(client, owner):
    book(client, owner["free"]["id"], slot_at(next_weekday(1), 9))
    with SessionLocal() as db, db.begin():
        set_context(db)
        alpha_id = db.scalar(select(Tenant.id).where(Tenant.slug == "alpha"))
    with tenant_session(alpha_id) as db:
        assert db.scalar(select(func.count()).select_from(Booking)) == 1


def test_service_changes_invalidate_cached_slots(client, owner):
    day = next_weekday(1).isoformat()
    params = {"service_id": owner["free"]["id"], "date": day}
    first = client.get("/public/alpha/slots", params=params).json()["slots"]
    client.patch(f"/admin/services/{owner['free']['id']}", headers=owner["headers"], json={"duration_minutes": 120})
    longer = client.get("/public/alpha/slots", params=params).json()["slots"]
    assert len(longer) < len(first)  # pas de résultat périmé servi depuis le cache
    client.delete(f"/admin/services/{owner['free']['id']}", headers=owner["headers"])
    assert client.get("/public/alpha/slots", params=params).status_code == 404
    assert client.get("/public/alpha/slots", params=params).status_code == 404  # servi par le cache négatif
    assert client.get("/public/nope/slots", params=params).status_code == 404
