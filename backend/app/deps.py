"""Dépendances FastAPI : sessions, authentification, contexte tenant et rôles."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import cache
from .config import get_settings
from .db import SessionLocal, set_context
from .models import Membership, Role, Tenant, User
from .security import decode_token


def get_tenant_by_slug(db: Session, slug: str) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise HTTPException(404, "entreprise inconnue")
    return tenant


@contextmanager
def public_tx(slug: str, lock_timeout_ms: int | None = None) -> Iterator[tuple[Session, Tenant]]:
    """Transaction publique ouverte ET validée dans le même appel.

    À utiliser pour les écritures : avec une dépendance FastAPI à `yield`, le commit a lieu dans la
    phase de nettoyage, qui réclame un thread du pool. Si tous les threads attendent un verrou tenu par
    une transaction pas encore validée, plus personne ne peut valider : interblocage (constaté au test
    de charge). Ici, le verrou est relâché avant la fin de l'appel.
    """
    with SessionLocal() as db, db.begin():
        if lock_timeout_ms:
            db.execute(text(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'"))
        set_context(db)
        tenant = get_tenant_by_slug(db, slug)
        set_context(db, tenant.id)
        yield db, tenant


def public_db(slug: str) -> Iterator[tuple[Session, Tenant]]:
    """Session publique pour /public/{slug} : le tenant vient de l'URL."""
    with SessionLocal() as db, db.begin():
        set_context(db)
        tenant = get_tenant_by_slug(db, slug)
        set_context(db, tenant.id)
        yield db, tenant


def current_user_id(authorization: str = Header(default="")) -> uuid.UUID:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentification requise", headers={"WWW-Authenticate": "Bearer"})
    try:
        return decode_token(token)
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "jeton invalide ou expiré") from None


def user_db(user_id: uuid.UUID = Depends(current_user_id)) -> Iterator[tuple[Session, User]]:
    with SessionLocal() as db, db.begin():
        set_context(db, None, user_id)
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(401, "utilisateur inconnu")
        yield db, user


@dataclass
class Ctx:
    db: Session
    user: User
    tenant: Tenant
    role: Role

    def require(self, *roles: Role) -> None:
        if self.role not in roles:
            raise HTTPException(403, "droits insuffisants")


def tenant_ctx(x_tenant: str = Header(alias="X-Tenant"), user_id: uuid.UUID = Depends(current_user_id)) -> Iterator[Ctx]:
    """Contexte d'administration : utilisateur authentifié + tenant choisi (en-tête X-Tenant) + rôle."""
    with SessionLocal() as db, db.begin():
        set_context(db, None, user_id)
        tenant = get_tenant_by_slug(db, x_tenant)
        membership = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.tenant_id == tenant.id))
        if membership is None:
            raise HTTPException(403, "vous n'êtes pas membre de cette entreprise")
        set_context(db, tenant.id, user_id)
        yield Ctx(db=db, user=membership.user, tenant=tenant, role=membership.role)


def rate_limit(scope: str, limit_attr: str):
    def check(request: Request) -> None:
        limit = getattr(get_settings(), limit_attr)
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
        if not cache.allow(f"{scope}:{ip}", limit):
            raise HTTPException(429, "trop de requêtes, réessayez dans une minute", headers={"Retry-After": "60"})

    return check
