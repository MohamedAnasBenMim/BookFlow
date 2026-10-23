"""Parcours client : créneaux, réservation, paiement, annulation, concurrence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import notify
from app.main import app
from app.worker import run_once

from .conftest import next_weekday

PARIS = ZoneInfo("Europe/Paris")


def slot_at(day, hour, minute=0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS).astimezone(UTC).isoformat()


def book(client, service_id, start, email="client@test.dev"):
    return client.post(
        "/public/alpha/bookings", json={"service_id": service_id, "start": start, "customer_name": "Client", "customer_email": email}
    )


def test_slots_follow_opening_hours(client, owner):
    monday = next_weekday(0)
    slots = client.get("/public/alpha/slots", params={"service_id": owner["paid"]["id"], "date": monday.isoformat()}).json()["slots"]
    local = [datetime.fromisoformat(s["start"]).astimezone(PARIS) for s in slots]
    assert local[0].strftime("%H:%M") == "09:00"
    assert local[-1].strftime("%H:%M") == "17:00"  # 60 min : dernier départ 17h pour finir à 18h
    assert len(local) == 33  # pas de 15 min de 9h00 à 17h00


def test_no_slots_on_closed_day(client, owner):
    sunday = next_weekday(6)
    r = client.get("/public/alpha/slots", params={"service_id": owner["paid"]["id"], "date": sunday.isoformat()})
    assert r.json()["slots"] == []


def test_free_booking_is_confirmed_and_slot_disappears(client, owner):
    day = next_weekday(1)
    r = book(client, owner["free"]["id"], slot_at(day, 10))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["booking"]["status"] == "confirmed" and body["checkout_url"] is None
    slots = client.get("/public/alpha/slots", params={"service_id": owner["free"]["id"], "date": day.isoformat()}).json()["slots"]
    starts = {datetime.fromisoformat(s["start"]) for s in slots}
    at = lambda h, m=0: datetime.fromisoformat(slot_at(day, h, m))  # noqa: E731
    # 30 min réservées à 10h : 9h45 (chevauche), 10h00 et 10h15 disparaissent ; 9h30 et 10h30 restent
    assert at(10) not in starts and at(9, 45) not in starts and at(10, 15) not in starts
    assert at(9, 30) in starts and at(10, 30) in starts


def test_paid_booking_flow_with_fake_payment(client, owner):
    day = next_weekday(2)
    r = book(client, owner["paid"]["id"], slot_at(day, 14))
    created = r.json()
    assert created["booking"]["status"] == "pending_payment"
    assert "/payments/fake/alpha/" in created["checkout_url"]
    pay = client.get(created["checkout_url"].replace("http://localhost:8000", ""), follow_redirects=False)
    assert pay.status_code == 303 and "paid=1" in pay.headers["location"]
    bid, token = created["booking"]["id"], created["access_token"]
    assert client.get(f"/public/alpha/bookings/{bid}", params={"token": token}).json()["status"] == "confirmed"
    # paiement rejoué : idempotent
    assert client.get(created["checkout_url"].replace("http://localhost:8000", ""), follow_redirects=False).status_code == 303


def test_wrong_token_cannot_read_or_cancel(client, owner):
    created = book(client, owner["free"]["id"], slot_at(next_weekday(3), 11)).json()
    bid = created["booking"]["id"]
    assert client.get(f"/public/alpha/bookings/{bid}", params={"token": "nope"}).status_code == 404
    assert client.post(f"/public/alpha/bookings/{bid}/cancel", params={"token": "nope"}).status_code == 404


def test_cancel_frees_slot_and_sends_email(client, owner):
    day = next_weekday(3)
    created = book(client, owner["free"]["id"], slot_at(day, 15)).json()
    r = client.post(f"/public/alpha/bookings/{created['booking']['id']}/cancel", params={"token": created["access_token"]})
    assert r.json()["status"] == "cancelled"
    assert book(client, owner["free"]["id"], slot_at(day, 15), email="other@test.dev").status_code == 201
    run_once()
    subjects = [m["Subject"] for m in notify.OUTBOX]
    assert any("annulé" in s for s in subjects)


def test_taken_or_invalid_slot_is_rejected(client, owner):
    day = next_weekday(4)
    assert book(client, owner["free"]["id"], slot_at(day, 9)).status_code == 201
    assert book(client, owner["free"]["id"], slot_at(day, 9), email="b@test.dev").status_code == 409
    assert book(client, owner["free"]["id"], slot_at(day, 9, 7)).status_code == 409  # pas aligné sur la grille
    assert book(client, owner["free"]["id"], slot_at(day, 20)).status_code == 409  # hors horaires


def test_concurrent_bookings_never_double_book(owner):
    """20 clients réservent le même créneau en même temps : exactement 1 réussit (contrainte d'exclusion)."""
    day = next_weekday(1, min_days=9)
    start = slot_at(day, 16)

    def attempt(i):
        with TestClient(app) as c:
            return book(c, owner["free"]["id"], start, email=f"c{i}@test.dev").status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(attempt, range(20)))
    assert codes.count(201) == 1 and codes.count(409) == 19


def test_second_staff_member_doubles_capacity(client, owner):
    h = owner["headers"]
    staff = client.post("/admin/staff", headers=h, json={"email": "bob@alpha.dev", "name": "Bob", "password": "password123"}).json()
    rules = [{"weekday": d, "start_time": "09:00", "end_time": "18:00"} for d in range(5)]
    assert client.put("/admin/availability", headers=h, params={"staff_id": staff["user_id"]}, json=rules).status_code == 200
    day = next_weekday(0, min_days=9)
    first, second = book(client, owner["free"]["id"], slot_at(day, 9)), book(client, owner["free"]["id"], slot_at(day, 9), "x@t.dev")
    assert first.status_code == second.status_code == 201
    assert first.json()["booking"]["staff_id"] != second.json()["booking"]["staff_id"]
    assert book(client, owner["free"]["id"], slot_at(day, 9), "y@t.dev").status_code == 409


def test_unpaid_booking_expires_and_releases_slot(client, owner, settings):
    day = next_weekday(2, min_days=9)
    created = book(client, owner["paid"]["id"], slot_at(day, 9)).json()
    later = datetime.now(UTC) + timedelta(minutes=settings.pending_payment_ttl_minutes + 1)
    assert run_once(now=later)["expired"] == 1
    assert (
        client.get(f"/public/alpha/bookings/{created['booking']['id']}", params={"token": created["access_token"]}).json()["status"]
        == "cancelled"
    )
    assert book(client, owner["paid"]["id"], slot_at(day, 9), "z@t.dev").status_code == 201


def test_confirmation_and_reminder_emails(client, owner):
    day = next_weekday(1, min_days=5)
    book(client, owner["free"]["id"], slot_at(day, 11))
    assert run_once()["sent"] == 1  # confirmation immédiate
    assert "confirmé" in notify.OUTBOX[0]["Subject"]
    assert run_once()["sent"] == 0  # rien de plus avant l'heure du rappel
    assert run_once(now=datetime.fromisoformat(slot_at(day, 11)) - timedelta(hours=23))["sent"] == 1  # J-1
    assert "Rappel" in notify.OUTBOX[1]["Subject"]


def test_slots_validation(client, owner):
    far = (datetime.now(UTC) + timedelta(days=400)).date().isoformat()
    assert client.get("/public/alpha/slots", params={"service_id": owner["free"]["id"], "date": far}).status_code == 422
    assert client.get("/public/unknown").status_code == 404
