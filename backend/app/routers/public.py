"""API publique : page de réservation d'une entreprise (sans compte)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import cache
from ..config import get_settings
from ..db import SessionLocal, set_context
from ..deps import public_db, public_tx, rate_limit
from ..models import Booking, Service, Tenant
from ..payments import checkout_url
from ..scheduling import SlotUnavailable, cached_slots, cancel_booking, create_booking
from ..schemas import BookingCreatedOut, BookingIn, BookingOut, PublicTenantOut, ServiceOut, SlotsOut

router = APIRouter(prefix="/public/{slug}", tags=["public"])
Pub = tuple[Session, Tenant]


def booking_out(b: Booking) -> BookingOut:
    return BookingOut.model_validate(
        {**{c: getattr(b, c) for c in BookingOut.model_fields if c != "service_name"}, "service_name": b.service.name}
    )


def _active_service(db: Session, tenant: Tenant, service_id: uuid.UUID) -> Service:
    service = db.get(Service, service_id)
    if service is None or service.tenant_id != tenant.id or not service.active:
        raise HTTPException(404, "prestation inconnue")
    return service


def _booking_with_token(db: Session, booking_id: uuid.UUID, token: str) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None or not secrets.compare_digest(booking.access_token, token):
        raise HTTPException(404, "réservation introuvable")
    return booking


@router.get("", response_model=PublicTenantOut)
def tenant_page(ctx: Pub = Depends(public_db)) -> PublicTenantOut:
    db, tenant = ctx
    services = db.scalars(select(Service).where(Service.active.is_(True)).order_by(Service.price_cents)).all()
    return PublicTenantOut(
        slug=tenant.slug,
        name=tenant.name,
        timezone=tenant.timezone,
        currency=tenant.currency,
        services=[ServiceOut.model_validate(s) for s in services],
    )


def _load_tenant(slug: str) -> dict | None:
    with SessionLocal() as db, db.begin():
        set_context(db)
        t = db.scalar(select(Tenant).where(Tenant.slug == slug))
        return {"id": t.id, "timezone": t.timezone} if t else None


@router.get("/slots", response_model=SlotsOut)
def slots(slug: str, service_id: uuid.UUID, day: date = Query(alias="date")) -> SlotsOut:
    """Chemin le plus sollicité : un résultat en cache est servi sans aucune requête SQL.

    La clé de cache couvre la prestation et le jour ; toute réservation, annulation ou modification
    des prestations / horaires du tenant invalide ses entrées (numéro de version dans Redis).
    """
    today = datetime.now(UTC).date()
    if not (today - timedelta(days=1) <= day <= today + timedelta(days=get_settings().max_days_ahead)):
        raise HTTPException(422, "date hors de la période réservable")
    info = cache.tenant_by_slug(slug, _load_tenant)
    if info is None:
        raise HTTPException(404, "entreprise inconnue")
    key = f"{service_id}:{day.isoformat()}"
    hit = cache.get_slots(info["id"], key)
    if hit is not None:
        if hit == ["__inactive__"]:
            raise HTTPException(404, "prestation inconnue")
        return SlotsOut(date=day, service_id=service_id, slots=hit)
    with SessionLocal() as db, db.begin():
        set_context(db, info["id"])
        tenant = db.get(Tenant, info["id"])
        try:
            service = _active_service(db, tenant, service_id)
        except HTTPException:
            cache.set_slots(info["id"], key, ["__inactive__"])  # évite de marteler la base avec un id invalide
            raise
        return SlotsOut(date=day, service_id=service.id, slots=cached_slots(db, tenant, service, day))


@router.post(
    "/bookings",
    response_model=BookingCreatedOut,
    status_code=201,
    dependencies=[Depends(rate_limit("booking", "rate_limit_bookings_per_minute"))],
)
def book(slug: str, body: BookingIn) -> BookingCreatedOut:
    try:
        with public_tx(slug, lock_timeout_ms=3000) as (db, tenant):
            service = _active_service(db, tenant, body.service_id)
            booking = create_booking(db, tenant, service, body.start, body.customer_name, body.customer_email, body.staff_id)
            url = checkout_url(booking, tenant, service.name)
            out = BookingCreatedOut(booking=booking_out(booking), access_token=booking.access_token, checkout_url=url)
    except SlotUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    except OperationalError as exc:  # lock_timeout : forte contention sur ce créneau
        if "lock timeout" not in str(exc).lower():
            raise
        raise HTTPException(409, "créneau très demandé, réessayez") from None
    return out


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: uuid.UUID, token: str, ctx: Pub = Depends(public_db)) -> BookingOut:
    db, _ = ctx
    return booking_out(_booking_with_token(db, booking_id, token))


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel(slug: str, booking_id: uuid.UUID, token: str) -> BookingOut:
    with public_tx(slug) as (db, _):
        booking = _booking_with_token(db, booking_id, token)
        if booking.start_at <= datetime.now(UTC):
            raise HTTPException(409, "rendez-vous déjà passé")
        cancel_booking(db, booking)
        return booking_out(booking)
