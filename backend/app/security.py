"""Mots de passe (Argon2), jetons JWT et connexion Google."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from .config import get_settings

_hasher = PasswordHasher()
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, password)
    except VerificationError:
        return False


def create_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}, s.jwt_secret, "HS256")


def decode_token(token: str) -> uuid.UUID:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    return uuid.UUID(payload["sub"])


def random_token() -> str:
    return secrets.token_urlsafe(32)


@lru_cache
def _google_jwks() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GOOGLE_JWKS, cache_keys=True)


def verify_google_id_token(id_token: str) -> dict:
    """Vérifie un jeton « Sign in with Google » : signature (clés publiques Google), audience, émetteur, expiration."""
    client_id = get_settings().google_client_id
    if not client_id:
        raise ValueError("connexion Google non configurée")
    key = _google_jwks().get_signing_key_from_jwt(id_token).key
    claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=client_id, issuer=GOOGLE_ISSUERS)
    if not claims.get("email_verified"):
        raise ValueError("email Google non vérifié")
    return claims
