"""Données de démonstration : deux entreprises, pour montrer l'isolation multi-tenant.

    python -m app.seed
Compte démo : demo@bookflow.dev / demo1234 (propriétaire de « Studio Zen »).
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import select

from .db import global_session, set_context
from .models import AvailabilityRule, Membership, Role, Service, Tenant, User
from .security import hash_password

DEMO = [
    {
        "slug": "studio-zen",
        "name": "Studio Zen — Yoga & Bien-être",
        "owner": ("demo@bookflow.dev", "Camille Martin"),
        "staff": [("lea@bookflow.dev", "Léa Bernard")],
        "services": [
            ("Cours de yoga individuel", 60, 4500, "Séance personnalisée, tous niveaux."),
            ("Massage relaxant", 45, 5500, "Massage aux huiles essentielles."),
            ("Appel découverte", 15, 0, "15 minutes pour faire connaissance, gratuit."),
        ],
    },
    {
        "slug": "barber-lyon",
        "name": "Barber Lyon",
        "owner": ("barber@bookflow.dev", "Yanis Haddad"),
        "staff": [],
        "services": [("Coupe homme", 30, 2500, ""), ("Coupe + barbe", 45, 3500, "")],
    },
]


def seed() -> None:
    with global_session() as db:
        for t in DEMO:
            if db.scalar(select(Tenant).where(Tenant.slug == t["slug"])):
                continue
            tenant = Tenant(slug=t["slug"], name=t["name"])
            db.add(tenant)
            db.flush()
            set_context(db, tenant.id)
            people = [(t["owner"], Role.owner)] + [(s, Role.staff) for s in t["staff"]]
            for (email, name), role in people:
                user = db.scalar(select(User).where(User.email == email))
                if user is None:
                    user = User(email=email, name=name, password_hash=hash_password("demo1234"))
                    db.add(user)
                    db.flush()
                db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
                for weekday in range(6):  # lundi -> samedi
                    db.add(
                        AvailabilityRule(tenant_id=tenant.id, staff_id=user.id, weekday=weekday, start_time=time(9), end_time=time(12, 30))
                    )
                    db.add(AvailabilityRule(tenant_id=tenant.id, staff_id=user.id, weekday=weekday, start_time=time(14), end_time=time(19)))
            for name, minutes, price, desc in t["services"]:
                db.add(Service(tenant_id=tenant.id, name=name, duration_minutes=minutes, price_cents=price, description=desc))
            db.flush()
            set_context(db)
            print(f"créé : {t['slug']}")


if __name__ == "__main__":
    seed()
