"""API d'administration (tableau de bord) : en-tête Authorization + X-Tenant."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError

from ..db import invalidate_after_commit
from ..deps import Ctx, tenant_ctx
from ..models import AvailabilityRule, Booking, BookingStatus, Membership, Role, Service, User
from ..scheduling import cancel_booking
from ..schemas import BookingPage, RuleIn, RuleOut, ServiceIn, ServiceOut, ServicePatch, StaffIn, StaffOut, StatsOut
from ..security import hash_password
from .public import booking_out

router = APIRouter(prefix="/admin", tags=["admin"])
MANAGERS = (Role.owner, Role.admin)


# ---------- prestations ----------
@router.get("/services", response_model=list[ServiceOut])
def list_services(ctx: Ctx = Depends(tenant_ctx)) -> list[Service]:
    return list(ctx.db.scalars(select(Service).order_by(Service.name)))


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(body: ServiceIn, ctx: Ctx = Depends(tenant_ctx)) -> Service:
    ctx.require(*MANAGERS)
    service = Service(tenant_id=ctx.tenant.id, **body.model_dump())
    ctx.db.add(service)
    ctx.db.flush()
    invalidate_after_commit(ctx.db, ctx.tenant.id)
    return service


@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: uuid.UUID, body: ServicePatch, ctx: Ctx = Depends(tenant_ctx)) -> Service:
    ctx.require(*MANAGERS)
    service = ctx.db.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "prestation inconnue")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(service, k, v)
    invalidate_after_commit(ctx.db, ctx.tenant.id)  # durée ou activation modifiées : les créneaux en cache sont périmés
    return service


@router.delete("/services/{service_id}", status_code=204)
def archive_service(service_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)) -> Response:
    """Archive (désactive) : les réservations passées gardent leur prestation."""
    ctx.require(*MANAGERS)
    service = ctx.db.get(Service, service_id)
    if service is None:
        raise HTTPException(404, "prestation inconnue")
    service.active = False
    invalidate_after_commit(ctx.db, ctx.tenant.id)
    return Response(status_code=204)


# ---------- réservations ----------
def _encode(start: datetime, bid: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{start.isoformat()}|{bid}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        start, bid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(start), uuid.UUID(bid)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "curseur invalide") from None


@router.get("/bookings", response_model=BookingPage)
def list_bookings(
    ctx: Ctx = Depends(tenant_ctx),
    start_from: datetime | None = Query(default=None, alias="from"),
    status: BookingStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> BookingPage:
    """Pagination par curseur (keyset) : stable et rapide même avec des milliers de réservations."""
    q = select(Booking)
    if ctx.role == Role.staff:
        q = q.where(Booking.staff_id == ctx.user.id)  # un membre de l'équipe ne voit que son planning
    if start_from:
        q = q.where(Booking.start_at >= start_from)
    if status:
        q = q.where(Booking.status == status)
    if cursor:
        q = q.where(tuple_(Booking.start_at, Booking.id) > tuple_(*_decode(cursor)))
    rows = ctx.db.scalars(q.order_by(Booking.start_at, Booking.id).limit(limit + 1)).all()
    items, more = rows[:limit], len(rows) > limit
    return BookingPage(items=[booking_out(b) for b in items], next_cursor=_encode(items[-1].start_at, items[-1].id) if more else None)


@router.post("/bookings/{booking_id}/cancel")
def admin_cancel(booking_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx)) -> dict:
    booking = ctx.db.get(Booking, booking_id)
    if booking is None or (ctx.role == Role.staff and booking.staff_id != ctx.user.id):
        raise HTTPException(404, "réservation introuvable")
    cancel_booking(ctx.db, booking)
    return {"id": str(booking.id), "status": booking.status.value}


# ---------- disponibilités ----------
@router.get("/availability", response_model=list[RuleOut])
def get_availability(staff_id: uuid.UUID | None = None, ctx: Ctx = Depends(tenant_ctx)) -> list[AvailabilityRule]:
    staff = staff_id or ctx.user.id
    return list(
        ctx.db.scalars(
            select(AvailabilityRule)
            .where(AvailabilityRule.staff_id == staff)
            .order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)
        )
    )


@router.put("/availability", response_model=list[RuleOut])
def set_availability(rules: list[RuleIn], staff_id: uuid.UUID | None = None, ctx: Ctx = Depends(tenant_ctx)) -> list[AvailabilityRule]:
    staff = staff_id or ctx.user.id
    if staff != ctx.user.id:
        ctx.require(*MANAGERS)
    if not ctx.db.scalar(select(Membership).where(Membership.user_id == staff, Membership.tenant_id == ctx.tenant.id)):
        raise HTTPException(404, "membre inconnu")
    for r in ctx.db.scalars(select(AvailabilityRule).where(AvailabilityRule.staff_id == staff)):
        ctx.db.delete(r)
    new = [AvailabilityRule(tenant_id=ctx.tenant.id, staff_id=staff, **r.model_dump()) for r in rules]
    ctx.db.add_all(new)
    ctx.db.flush()
    invalidate_after_commit(ctx.db, ctx.tenant.id)
    return new


# ---------- équipe ----------
@router.get("/staff", response_model=list[StaffOut])
def list_staff(ctx: Ctx = Depends(tenant_ctx)) -> list[StaffOut]:
    members = ctx.db.scalars(select(Membership).where(Membership.tenant_id == ctx.tenant.id)).all()
    return [StaffOut(user_id=m.user_id, email=m.user.email, name=m.user.name, role=m.role) for m in members]


@router.post("/staff", response_model=StaffOut, status_code=201)
def add_staff(body: StaffIn, ctx: Ctx = Depends(tenant_ctx)) -> StaffOut:
    ctx.require(*MANAGERS)
    if body.role == Role.owner:
        raise HTTPException(422, "un seul propriétaire par entreprise")
    user = ctx.db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password))
        ctx.db.add(user)
        ctx.db.flush()
    try:
        with ctx.db.begin_nested():
            ctx.db.add(Membership(tenant_id=ctx.tenant.id, user_id=user.id, role=body.role))
            ctx.db.flush()
    except IntegrityError:
        raise HTTPException(409, "déjà membre") from None
    return StaffOut(user_id=user.id, email=user.email, name=user.name, role=body.role)


# ---------- statistiques ----------
@router.get("/stats", response_model=StatsOut)
def stats(ctx: Ctx = Depends(tenant_ctx)) -> StatsOut:
    ctx.require(*MANAGERS)
    now = datetime.now(UTC)
    db = ctx.db
    upcoming = db.scalar(
        select(func.count())
        .select_from(Booking)
        .where(Booking.status == BookingStatus.confirmed, Booking.start_at >= now, Booking.start_at < now + timedelta(days=7))
    )
    revenue = db.scalar(
        select(func.coalesce(func.sum(Booking.price_cents), 0)).where(
            Booking.status == BookingStatus.confirmed, Booking.start_at >= now - timedelta(days=30), Booking.start_at < now
        )
    )
    recent = select(Booking.status).where(Booking.created_at >= now - timedelta(days=30), Booking.status != BookingStatus.pending_payment)
    statuses = db.scalars(recent).all()
    cancelled = sum(1 for s in statuses if s == BookingStatus.cancelled)
    return StatsOut(
        bookings_next_7_days=upcoming or 0,
        revenue_cents_last_30_days=int(revenue or 0),
        cancellation_rate_last_30_days=round(cancelled / len(statuses), 3) if statuses else 0.0,
    )
