"""Emails transactionnels (confirmation, rappel, annulation)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from .config import get_settings
from .models import Booking, Tenant

log = logging.getLogger("bookflow.email")
OUTBOX: list[EmailMessage] = []  # backend « memory » utilisé par les tests

SUBJECTS = {
    "confirmation": "Votre rendez-vous est confirmé",
    "reminder": "Rappel : votre rendez-vous approche",
    "cancellation": "Votre rendez-vous a été annulé",
}


def render(kind: str, booking: Booking, tenant: Tenant) -> EmailMessage:
    s = get_settings()
    when = booking.start_at.astimezone(ZoneInfo(tenant.timezone)).strftime("%d/%m/%Y à %H:%M")
    link = f"{s.frontend_url}/{tenant.slug}/booking/{booking.id}?token={booking.access_token}"
    msg = EmailMessage()
    msg["From"], msg["To"] = s.email_from, booking.customer_email
    msg["Subject"] = f"{SUBJECTS[kind]} — {tenant.name}"
    msg.set_content(
        f"Bonjour {booking.customer_name},\n\n"
        f"{SUBJECTS[kind]} : {booking.service.name} chez {tenant.name}, le {when}.\n\n"
        f"Consulter ou annuler : {link}\n"
    )
    return msg


def send(msg: EmailMessage) -> None:
    s = get_settings()
    if s.email_backend == "smtp":
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
    elif s.email_backend == "memory":
        OUTBOX.append(msg)
    else:
        log.info("email -> %s | %s", msg["To"], msg["Subject"])
