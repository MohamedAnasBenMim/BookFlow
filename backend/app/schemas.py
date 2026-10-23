"""Schémas d'entrée / sortie de l'API."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import BookingStatus, Role

SLUG = r"^[a-z0-9](?:[a-z0-9-]{1,58}[a-z0-9])$"


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    business_name: str = Field(min_length=2, max_length=120)
    slug: str = Field(pattern=SLUG)
    timezone: str = "Europe/Paris"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleIn(BaseModel):
    id_token: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MembershipOut(BaseModel):
    tenant_slug: str
    tenant_name: str
    role: Role


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    memberships: list[MembershipOut]


# ---------- services ----------
class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    duration_minutes: int = Field(ge=5, le=480)
    price_cents: int = Field(ge=0, le=1_000_000)
    active: bool = True


class ServicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    price_cents: int | None = Field(default=None, ge=0, le=1_000_000)
    active: bool | None = None


class ServiceOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    duration_minutes: int
    price_cents: int
    active: bool


class PublicTenantOut(BaseModel):
    slug: str
    name: str
    timezone: str
    currency: str
    services: list[ServiceOut]


# ---------- disponibilités ----------
class RuleIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    end_time: time

    @field_validator("end_time")
    @classmethod
    def after_start(cls, v: time, info) -> time:
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("end_time doit être après start_time")
        return v


class RuleOut(ORM):
    weekday: int
    start_time: time
    end_time: time


class SlotOut(BaseModel):
    start: datetime
    staff_ids: list[uuid.UUID]


class SlotsOut(BaseModel):
    date: date
    service_id: uuid.UUID
    slots: list[SlotOut]


# ---------- réservations ----------
class BookingIn(BaseModel):
    service_id: uuid.UUID
    start: datetime
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: EmailStr
    staff_id: uuid.UUID | None = None


class BookingOut(ORM):
    id: uuid.UUID
    service_id: uuid.UUID
    service_name: str
    staff_id: uuid.UUID
    customer_name: str
    customer_email: str
    start_at: datetime
    end_at: datetime
    status: BookingStatus
    price_cents: int


class BookingCreatedOut(BaseModel):
    booking: BookingOut
    access_token: str
    checkout_url: str | None


class BookingPage(BaseModel):
    items: list[BookingOut]
    next_cursor: str | None


class StaffIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.staff


class StaffOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: Role


class StatsOut(BaseModel):
    bookings_next_7_days: int
    revenue_cents_last_30_days: int
    cancellation_rate_last_30_days: float
