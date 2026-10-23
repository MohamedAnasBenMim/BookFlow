"""Connexion à la base et sessions liées à un tenant.

`tenant_session(tenant_id)` ouvre une transaction et positionne `app.tenant_id` (SET LOCAL) :
les politiques Row-Level Security de PostgreSQL filtrent alors automatiquement toutes les
lignes des autres tenants. Après le commit, la variable disparaît : une requête hors transaction
ne voit rien, ce qui échoue « fermé » plutôt qu'« ouvert ».
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from . import cache
from .config import get_settings

engine = create_engine(get_settings().database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def invalidate_after_commit(session: Session, tenant_id: uuid.UUID) -> None:
    """Invalide le cache des créneaux du tenant, mais seulement APRÈS le commit.

    Invalider avant le commit laisserait une fenêtre où une lecture concurrente recalcule les créneaux
    depuis l'état non encore validé et remet en cache un résultat périmé.
    """
    session.info.setdefault("invalidate", set()).add(tenant_id)


@event.listens_for(SessionLocal, "after_commit")
def _flush_invalidations(session: Session) -> None:
    for tenant_id in session.info.pop("invalidate", set()):
        cache.invalidate(tenant_id)


@event.listens_for(SessionLocal, "after_rollback")
def _drop_invalidations(session: Session) -> None:
    session.info.pop("invalidate", None)


def set_context(session: Session, tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
        {"t": str(tenant_id) if tenant_id else "", "u": str(user_id) if user_id else ""},
    )


@contextmanager
def tenant_session(tenant_id: uuid.UUID | None, user_id: uuid.UUID | None = None) -> Iterator[Session]:
    with SessionLocal() as session, session.begin():
        set_context(session, tenant_id, user_id)
        yield session


@contextmanager
def global_session() -> Iterator[Session]:
    """Session sans tenant : seules les tables globales (tenants, users) sont lisibles."""
    with SessionLocal() as session, session.begin():
        set_context(session)
        yield session
