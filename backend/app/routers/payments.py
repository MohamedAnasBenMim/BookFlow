"""Confirmation des paiements : webhook Stripe signé, ou paiement simulé en mode démo."""

from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from ..config import get_settings
from ..db import SessionLocal, set_context, tenant_session
from ..deps import get_tenant_by_slug
from ..models import Booking, ProcessedEvent
from ..payments import parse_stripe_event
from ..scheduling import confirm_payment

router = APIRouter(tags=["payments"])
log = logging.getLogger("bookflow.payments")


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")) -> dict:
    payload = await request.body()
    try:
        event = parse_stripe_event(payload, stripe_signature)
    except Exception as exc:  # noqa: BLE001 — signature absente, invalide ou expirée
        raise HTTPException(400, f"webhook refusé : {exc}") from None
    if event["type"] != "checkout.session.completed":
        return {"ignored": event["type"]}

    session = event["data"]["object"]
    tenant_id = uuid.UUID(session["metadata"]["tenant_id"])
    booking_id = uuid.UUID(session["metadata"]["booking_id"])
    with tenant_session(tenant_id) as db:
        try:
            with db.begin_nested():
                db.add(ProcessedEvent(id=event["id"]))
                db.flush()
        except IntegrityError:
            return {"duplicate": event["id"]}  # Stripe a renvoyé un événement déjà traité
        booking = db.get(Booking, booking_id)
        if booking is None:
            raise HTTPException(404, "réservation introuvable")
        confirmed = confirm_payment(db, booking, session["id"])
        if not confirmed:
            # payé après l'expiration du créneau : à rembourser, signalé dans les logs
            log.warning("paiement reçu pour une réservation %s non payable (%s)", booking.id, booking.status.value)
    return {"confirmed": confirmed}


@router.get("/payments/fake/{slug}/{booking_id}")
def fake_payment(slug: str, booking_id: uuid.UUID, token: str) -> RedirectResponse:
    """Paiement simulé (démo et tests). Désactivé dès que PAYMENTS_PROVIDER=stripe."""
    s = get_settings()
    if s.payments_provider != "fake":
        raise HTTPException(404, "paiement simulé désactivé")
    with SessionLocal() as db, db.begin():
        set_context(db)
        tenant = get_tenant_by_slug(db, slug)
        set_context(db, tenant.id)
        booking = db.get(Booking, booking_id)
        if booking is None or not secrets.compare_digest(booking.access_token, token):
            raise HTTPException(404, "réservation introuvable")
        confirm_payment(db, booking, f"fake_{booking.id.hex[:12]}")
    return RedirectResponse(f"{s.frontend_url}/{slug}/booking/{booking_id}?token={token}&paid=1", status_code=303)
