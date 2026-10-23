"""Tâches de fond : envoi des emails dus (outbox) et libération des créneaux non payés.

python -m app.worker            # boucle (toutes les 30 s)
python -m app.worker --once     # un passage (cron, tests)
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select

from .db import global_session, invalidate_after_commit, tenant_session
from .models import Booking, BookingStatus, Notification, Tenant
from .notify import render, send

log = logging.getLogger("bookflow.worker")
MAX_ATTEMPTS = 5


def run_once(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    stats = {"sent": 0, "failed": 0, "expired": 0}
    with global_session() as db:
        tenant_ids = db.scalars(select(Tenant.id)).all()
    for tid in tenant_ids:
        # une transaction par tenant : le RLS reste actif, comme pour les requêtes web
        with tenant_session(tid) as db:
            tenant = db.get(Tenant, tid)
            expired = db.scalars(select(Booking).where(Booking.status == BookingStatus.pending_payment, Booking.expires_at <= now)).all()
            for b in expired:
                b.status = BookingStatus.cancelled
            if expired:
                invalidate_after_commit(db, tid)
            stats["expired"] += len(expired)

            due = db.scalars(
                select(Notification)
                .where(Notification.sent_at.is_(None), Notification.send_at <= now, Notification.attempts < MAX_ATTEMPTS)
                .with_for_update(skip_locked=True)  # plusieurs workers peuvent tourner sans doublon
                .limit(200)
            ).all()
            for n in due:
                booking = db.get(Booking, n.booking_id)
                n.attempts += 1
                try:
                    send(render(n.kind, booking, tenant))
                    n.sent_at = now
                    stats["sent"] += 1
                except Exception as exc:  # noqa: BLE001 — réessai au prochain passage
                    log.warning("envoi %s échoué : %s", n.id, exc)
                    stats["failed"] += 1
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        log.info("passage worker : %s", run_once())
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
