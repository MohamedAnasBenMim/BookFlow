"""Redis : cache des créneaux et limitation de débit.

- Cache : les créneaux d'une journée sont coûteux à calculer (règles x réservations) et très lus.
  Chaque tenant a un numéro de version ; toute réservation ou annulation l'incrémente, ce qui
  invalide d'un coup toutes ses entrées sans avoir à les énumérer.
- Limitation : fenêtre glissante par clé (IP + route), implémentée avec un sorted set.
Sans Redis (REDIS_URL vide), le cache est désactivé et la limitation se fait en mémoire.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

import redis

from .config import get_settings

log = logging.getLogger(__name__)
_client: redis.Redis | None = None
_local_hits: dict[str, deque] = defaultdict(deque)
_local_lock = threading.Lock()


def client() -> redis.Redis | None:
    global _client
    url = get_settings().redis_url
    if not url:
        return None
    if _client is None:
        _client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5)
    return _client


def _version(r: redis.Redis, tenant_id: uuid.UUID) -> str:
    return r.get(f"bf:ver:{tenant_id}") or "0"


_tenants: dict[str, tuple[float, dict]] = {}
TENANT_TTL = 60.0


def tenant_by_slug(slug: str, loader) -> dict | None:
    """Cache mémoire (par processus) slug -> {id, timezone} : la donnée la plus lue et la plus stable."""
    now = time.monotonic()
    hit = _tenants.get(slug)
    if hit and now - hit[0] < TENANT_TTL:
        return hit[1]
    value = loader(slug)
    if value is not None:
        _tenants[slug] = (now, value)
    return value


def get_slots(tenant_id: uuid.UUID, key: str) -> list | None:
    r = client()
    if r is None:
        return None
    try:
        raw = r.get(f"bf:slots:{tenant_id}:{_version(r, tenant_id)}:{key}")
        return json.loads(raw) if raw else None
    except redis.RedisError as exc:  # le cache ne doit jamais casser une requête
        log.warning("cache indisponible : %s", exc)
        return None


def set_slots(tenant_id: uuid.UUID, key: str, value: list) -> None:
    r = client()
    if r is None:
        return
    try:
        r.set(f"bf:slots:{tenant_id}:{_version(r, tenant_id)}:{key}", json.dumps(value), ex=get_settings().slots_cache_ttl_seconds)
    except redis.RedisError as exc:
        log.warning("cache indisponible : %s", exc)


def invalidate(tenant_id: uuid.UUID) -> None:
    r = client()
    if r is None:
        return
    try:
        r.incr(f"bf:ver:{tenant_id}")
    except redis.RedisError as exc:
        log.warning("invalidation impossible : %s", exc)


def allow(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Fenêtre glissante : True si la requête est autorisée."""
    now = time.time()
    r = client()
    if r is not None:
        try:
            k = f"bf:rl:{key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(k, 0, now - window_seconds)
            pipe.zadd(k, {f"{now}:{uuid.uuid4().hex[:6]}": now})
            pipe.zcard(k)
            pipe.expire(k, window_seconds)
            count = pipe.execute()[2]
            return count <= limit
        except redis.RedisError as exc:
            log.warning("limitation Redis indisponible, repli mémoire : %s", exc)
    with _local_lock:
        hits = _local_hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        hits.append(now)
        return len(hits) <= limit
