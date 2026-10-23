"""Paiement : fournisseur factice (démo, tests) ou Stripe Checkout (mode test).

Le fournisseur renvoie une URL de paiement. La confirmation arrive ensuite :
- Stripe : par webhook signé (`checkout.session.completed`), traité de façon idempotente ;
- factice : par un lien de paiement simulé, actif uniquement si PAYMENTS_PROVIDER=fake.
"""

from __future__ import annotations

import stripe

from .config import get_settings
from .models import Booking, Tenant


def checkout_url(booking: Booking, tenant: Tenant, service_name: str) -> str | None:
    s = get_settings()
    if booking.price_cents == 0:
        return None
    success = f"{s.frontend_url}/{tenant.slug}/booking/{booking.id}?token={booking.access_token}"
    if s.payments_provider == "stripe":
        session = stripe.checkout.Session.create(
            api_key=s.stripe_secret_key,
            mode="payment",
            customer_email=booking.customer_email,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": tenant.currency,
                        "unit_amount": booking.price_cents,
                        "product_data": {"name": f"{service_name} — {tenant.name}"},
                    },
                }
            ],
            metadata={"booking_id": str(booking.id), "tenant_id": str(tenant.id)},
            expires_at=int(booking.expires_at.timestamp()) if booking.expires_at else None,
            success_url=success + "&paid=1",
            cancel_url=f"{s.frontend_url}/{tenant.slug}",
        )
        booking.payment_ref = session.id
        return session.url
    return f"{s.api_url}/payments/fake/{tenant.slug}/{booking.id}?token={booking.access_token}"


def parse_stripe_event(payload: bytes, signature: str) -> stripe.Event:
    """Vérifie la signature du webhook (rejette tout appel qui ne vient pas de Stripe)."""
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise ValueError("webhook Stripe non configuré")
    return stripe.Webhook.construct_event(payload, signature, secret)
