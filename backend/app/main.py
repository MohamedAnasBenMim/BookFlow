"""Application FastAPI."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import text

from . import __version__
from .config import get_settings
from .db import engine
from .routers import admin, auth, payments, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("bookflow")

app = FastAPI(
    title="BookFlow API",
    version=__version__,
    description="Prise de rendez-vous multi-entreprises : réservation publique, paiement, tableau de bord.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

REQUESTS = Counter("http_requests_total", "Requêtes HTTP", ["route", "method", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "Durée des requêtes", ["route"], buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5)
)


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")  # gabarit de route : évite l'explosion de cardinalité
    LATENCY.labels(path).observe(time.perf_counter() - t0)
    REQUESTS.labels(path, request.method, str(response.status_code)).inc()
    response.headers["X-Request-ID"] = rid
    return response


app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(public.router)
app.include_router(admin.router)
app.include_router(payments.router)


@app.get("/health", tags=["ops"])
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@app.get("/metrics", tags=["ops"])
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
