"""Calcul des créneaux disponibles et création des réservations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import cache
from .config import get_settings
from .db import invalidate_after_commit
from .models import AvailabilityRule, Booking, BookingStatus, Notification, Service, Tenant
from .security import random_token


class SlotUnavailable(Exception):
    """Le créneau demandé n'est pas (ou plus) libre."""


@dataclass(frozen=True)
class Slot:
    start: datetime
    staff_ids: tuple[uuid.UUID, ...]


def _active_filter(now: datetime):
    # une réservation en attente de paiement bloque le créneau jusqu'à son expiration
    return or_(
        Booking.status == BookingStatus.confirmed,
        and_(Booking.status == BookingStatus.pending_payment, Booking.expires_at > now),
    )


def compute_slots(db: Session, tenant: Tenant, service: Service, day: date, now: datetime | None = None) -> list[Slot]:
    s = get_settings()
    now = now or datetime.now(UTC)
    tz = ZoneInfo(tenant.timezone)
    duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=s.slot_step_minutes)
    earliest = now + timedelta(minutes=s.min_notice_minutes)

    # toute personne qui a des plages de disponibilité est réservable (owner, admin ou staff)
    rules = db.scalars(
        select(AvailabilityRule).where(AvailabilityRule.tenant_id == tenant.id, AvailabilityRule.weekday == day.weekday())
    ).all()
    if not rules:
        return []

    day_start = datetime.combine(day, datetime.min.time(), tz)
    day_end = day_start + timedelta(days=1)
    busy: dict[uuid.UUID, list[tuple[datetime, datetime]]] = {}
    for b in db.scalars(
        select(Booking).where(Booking.tenant_id == tenant.id, Booking.start_at < day_end, Booking.end_at > day_start, _active_filter(now))
    ).all():
        busy.setdefault(b.staff_id, []).append((b.start_at, b.end_at))

    by_start: dict[datetime, list[uuid.UUID]] = {}
    for rule in rules:
        cursor = datetime.combine(day, rule.start_time, tz)
        end = datetime.combine(day, rule.end_time, tz)
        while cursor + duration <= end:
            start_utc, end_utc = cursor.astimezone(UTC), (cursor + duration).astimezone(UTC)
            free = all(not (start_utc < e and end_utc > b) for b, e in busy.get(rule.staff_id, []))
            if free and start_utc >= earliest:
                by_start.setdefault(start_utc, []).append(rule.staff_id)
            cursor += step
    return [Slot(start=k, staff_ids=tuple(sorted(v, key=str))) for k, v in sorted(by_start.items())]


def cached_slots(db: Session, tenant: Tenant, service: Service, day: date) -> list[dict]:
    key = f"{service.id}:{day.isoformat()}"
    hit = cache.get_slots(tenant.id, key)
    if hit is not None:
        return hit
    slots = [{"start": sl.start.isoformat(), "staff_ids": [str(x) for x in sl.staff_ids]} for sl in compute_slots(db, tenant, service, day)]
    cache.set_slots(tenant.id, key, slots)
    return slots


def create_booking(
    db: Session,
    tenant: Tenant,
    service: Service,
    start: datetime,
    customer_name: str,
    customer_email: str,
    staff_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Booking:
    """Réserve un créneau. Le premier membre libre est choisi si `staff_id` n'est pas imposé.

    La vérification applicative est une première barrière ; la vraie garantie est la contrainte
    d'exclusion PostgreSQL `bookings_no_overlap`, qui rejette toute réservation concurrente.
    """
    s = get_settings()
    now = now or datetime.now(UTC)
    start = start.astimezone(UTC)
    tz = ZoneInfo(tenant.timezone)
    day = start.astimezone(tz).date()
    available = {sl.start: sl.staff_ids for sl in compute_slots(db, tenant, service, day, now)}
    candidates = [x for x in available.get(start, ()) if staff_id is None or x == staff_id]
    if not candidates:
        raise SlotUnavailable("créneau indisponible")

    for candidate in candidates:
        booking = Booking(
            tenant_id=tenant.id,
            service_id=service.id,
            staff_id=candidate,
            customer_name=customer_name.strip(),
            customer_email=customer_email.lower(),
            start_at=start,
            end_at=start + timedelta(minutes=service.duration_minutes),
            status=BookingStatus.pending_payment if service.price_cents > 0 else BookingStatus.confirmed,
            price_cents=service.price_cents,
            access_token=random_token(),
            expires_at=now + timedelta(minutes=s.pending_payment_ttl_minutes) if service.price_cents > 0 else None,
        )
        try:
            with db.begin_nested():  # savepoint : un conflit n'annule pas toute la transaction
                db.add(booking)
                db.flush()
        except IntegrityError:
            continue  # pris entre-temps par une requête concurrente : essayer le membre suivant
        if booking.status == BookingStatus.confirmed:
            schedule_notifications(db, booking, now)
        invalidate_after_commit(db, tenant.id)
        return booking
    raise SlotUnavailable("créneau pris entre-temps")


def schedule_notifications(db: Session, booking: Booking, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    db.add(Notification(tenant_id=booking.tenant_id, booking_id=booking.id, kind="confirmation", send_at=now))
    reminder_at = booking.start_at - timedelta(hours=get_settings().reminder_hours_before)
    if reminder_at > now:
        db.add(Notification(tenant_id=booking.tenant_id, booking_id=booking.id, kind="reminder", send_at=reminder_at))


def confirm_payment(db: Session, booking: Booking, payment_ref: str, now: datetime | None = None) -> bool:
    """Passe la réservation à « confirmée ». Idempotent : renvoie False si déjà traitée."""
    if booking.status != BookingStatus.pending_payment:
        return False
    booking.status = BookingStatus.confirmed
    booking.payment_ref = payment_ref
    booking.expires_at = None
    schedule_notifications(db, booking, now)
    return True


def cancel_booking(db: Session, booking: Booking, now: datetime | None = None) -> None:
    if booking.status == BookingStatus.cancelled:
        return
    was_confirmed = booking.status == BookingStatus.confirmed
    booking.status = BookingStatus.cancelled
    for n in db.scalars(select(Notification).where(Notification.booking_id == booking.id, Notification.sent_at.is_(None))):
        db.delete(n)
    if was_confirmed:
        db.add(Notification(tenant_id=booking.tenant_id, booking_id=booking.id, kind="cancellation", send_at=now or datetime.now(UTC)))
    invalidate_after_commit(db, booking.tenant_id)
