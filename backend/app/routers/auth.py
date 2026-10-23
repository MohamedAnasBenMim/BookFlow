from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import SessionLocal, set_context
from ..deps import rate_limit, user_db
from ..models import AvailabilityRule, Membership, Role, Tenant, User
from ..schemas import GoogleIn, LoginIn, MembershipOut, MeOut, RegisterIn, TokenOut
from ..security import create_token, hash_password, verify_google_id_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])

DEFAULT_HOURS = [(d, "09:00", "18:00") for d in range(5)]  # lun-ven 9h-18h à la création


@router.post(
    "/register", response_model=TokenOut, status_code=201, dependencies=[Depends(rate_limit("register", "rate_limit_login_per_minute"))]
)
def register(body: RegisterIn) -> TokenOut:
    """Crée un compte et son entreprise (le créateur en devient propriétaire)."""
    from datetime import time

    with SessionLocal() as db, db.begin():
        set_context(db)
        if db.scalar(select(User).where(User.email == body.email.lower())):
            raise HTTPException(409, "un compte existe déjà avec cet email")
        if db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
            raise HTTPException(409, "cette adresse de page est déjà prise")
        user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password))
        tenant = Tenant(slug=body.slug, name=body.business_name, timezone=body.timezone)
        db.add_all([user, tenant])
        db.flush()
        set_context(db, tenant.id, user.id)
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=Role.owner))
        for weekday, start, end in DEFAULT_HOURS:
            db.add(
                AvailabilityRule(
                    tenant_id=tenant.id,
                    staff_id=user.id,
                    weekday=weekday,
                    start_time=time.fromisoformat(start),
                    end_time=time.fromisoformat(end),
                )
            )
        try:
            db.flush()
        except IntegrityError:
            raise HTTPException(409, "compte ou adresse déjà utilisés") from None
        return TokenOut(access_token=create_token(user.id))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(rate_limit("login", "rate_limit_login_per_minute"))])
def login(body: LoginIn) -> TokenOut:
    with SessionLocal() as db, db.begin():
        set_context(db)
        user = db.scalar(select(User).where(User.email == body.email.lower()))
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(401, "email ou mot de passe incorrect")
        return TokenOut(access_token=create_token(user.id))


@router.post("/google", response_model=TokenOut)
def google(body: GoogleIn) -> TokenOut:
    """Connexion Google : le frontend obtient un ID token (Google Identity Services), le serveur le vérifie."""
    try:
        claims = verify_google_id_token(body.id_token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(401, f"jeton Google refusé : {exc}") from None
    with SessionLocal() as db, db.begin():
        set_context(db)
        user = db.scalar(select(User).where(User.google_sub == claims["sub"])) or db.scalar(
            select(User).where(User.email == claims["email"].lower())
        )
        if user is None:
            user = User(email=claims["email"].lower(), name=claims.get("name") or claims["email"], google_sub=claims["sub"])
            db.add(user)
        else:
            user.google_sub = claims["sub"]
        db.flush()
        return TokenOut(access_token=create_token(user.id))


@me_router.get("/me", response_model=MeOut)
def me(ctx: tuple[Session, User] = Depends(user_db)) -> MeOut:
    db, user = ctx
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        memberships=[MembershipOut(tenant_slug=m.tenant.slug, tenant_name=m.tenant.name, role=m.role) for m in memberships],
    )
