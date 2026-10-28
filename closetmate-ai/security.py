"""
security.py — passwords, JWT access tokens, rotating refresh tokens, and the
FastAPI auth dependencies.

Token model
-----------
* Access token  : short-lived (default 15 min) HS256 JWT, sent as
                  ``Authorization: Bearer <jwt>``. Verified without a DB hit.
* Refresh token : opaque random string (default 60 days). Only its SHA-256 is
                  stored. Every use rotates it; replaying an already-rotated
                  token is treated as theft and revokes all of that user's
                  sessions.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional, Tuple

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text

from database import db_session
from models.user import User
from settings import get_settings

log = logging.getLogger(__name__)

# bcrypt only uses the first 72 bytes (and bcrypt>=5 raises beyond that).
MAX_PASSWORD_BYTES = 72
_ACCESS = "access"


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode("utf-8")


def verify_password_or_dummy(password: str, password_hash: Optional[str]) -> bool:
    """Always burns one bcrypt comparison so 'unknown email' is not faster than 'wrong password'."""
    if password_hash is None:
        verify_password(password, _dummy_hash())
        return False
    return verify_password(password, password_hash)


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------

def create_access_token(user_id: str) -> Tuple[str, int]:
    """Return (jwt, expires_in_seconds)."""
    s = get_settings()
    now = _utcnow()
    lifetime = timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": user_id,
        "type": _ACCESS,
        "iss": s.jwt_issuer,
        "iat": now,
        "exp": now + lifetime,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), int(lifetime.total_seconds())


def decode_access_token(token: str) -> str:
    """Return the user_id inside a valid access token, or raise 401."""
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=["HS256"],          # never trust the token's own "alg"
            issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
            leeway=10,
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token") from None

    sub = payload.get("sub")
    if payload.get("type") != _ACCESS or not isinstance(sub, str) or not sub:
        raise _unauthorized("Invalid token")
    return sub


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_refresh_token(db, user_id: str) -> str:
    """Create and store a new refresh token; returns the raw value (shown once)."""
    s = get_settings()
    raw = secrets.token_urlsafe(48)
    now = _utcnow()
    db.execute(
        text("""INSERT INTO refresh_tokens (token_hash, user_id, created_at, expires_at)
                VALUES (:h, :u, :c, :e)"""),
        {
            "h": _hash_token(raw),
            "u": user_id,
            "c": now.isoformat(),
            "e": (now + timedelta(days=s.refresh_token_days)).isoformat(),
        },
    )
    # Housekeeping: drop this user's expired rows so the table stays small.
    db.execute(
        text("DELETE FROM refresh_tokens WHERE user_id = :u AND expires_at < :now"),
        {"u": user_id, "now": now.isoformat()},
    )
    return raw


def rotate_refresh_token(db, raw: str) -> Tuple[str, str]:
    """Validate ``raw``, revoke it, and return (user_id, new_raw_refresh_token)."""
    now = _utcnow()
    token_hash = _hash_token(raw)
    row = db.execute(
        text("SELECT user_id, expires_at, revoked_at FROM refresh_tokens WHERE token_hash = :h"),
        {"h": token_hash},
    ).fetchone()
    if row is None:
        raise _unauthorized("Invalid refresh token")

    user_id = row["user_id"]
    if row["revoked_at"] is not None:
        # An already-rotated token came back: someone is replaying a stolen copy.
        db.execute(
            text("UPDATE refresh_tokens SET revoked_at = :now WHERE user_id = :u AND revoked_at IS NULL"),
            {"now": now.isoformat(), "u": user_id},
        )
        db.commit()   # must persist before we raise (raising rolls back the session)
        log.warning("refresh token reuse detected; revoked all sessions user_id=%s", user_id)
        raise _unauthorized("Refresh token reuse detected")

    if datetime.fromisoformat(str(row["expires_at"])) <= now:
        raise _unauthorized("Refresh token expired")

    result = db.execute(
        text("UPDATE refresh_tokens SET revoked_at = :now WHERE token_hash = :h AND revoked_at IS NULL"),
        {"now": now.isoformat(), "h": token_hash},
    )
    if result.rowcount != 1:
        # Lost a race with a concurrent use of the same token. Two parties hold it, and
        # one may be a thief who won the race — so treat it exactly like reuse.
        revoke_all_refresh_tokens(db, user_id)
        db.commit()
        log.warning("concurrent refresh-token use; revoked all sessions user_id=%s", user_id)
        raise _unauthorized("Invalid refresh token")

    new_raw = issue_refresh_token(db, user_id)
    db.commit()
    return user_id, new_raw


def revoke_refresh_token(db, raw: str) -> None:
    db.execute(
        text("UPDATE refresh_tokens SET revoked_at = :now WHERE token_hash = :h AND revoked_at IS NULL"),
        {"now": _utcnow().isoformat(), "h": _hash_token(raw)},
    )


def revoke_all_refresh_tokens(db, user_id: str) -> None:
    db.execute(
        text("UPDATE refresh_tokens SET revoked_at = :now WHERE user_id = :u AND revoked_at IS NULL"),
        {"now": _utcnow().isoformat(), "u": user_id},
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def current_user_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    """Authenticate from the JWT alone (no DB round-trip) and return the user_id."""
    if not authorization:
        raise _unauthorized("Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized("Invalid Authorization header")
    return decode_access_token(parts[1])


def row_to_user(row) -> User:
    return User(
        user_id=row["user_id"],
        name=row["name"],
        email=row["email"],
        gender=row["gender"],
        body_shape=row["body_shape"],
        skin_tone=row["skin_tone"],
        style_preference=row["style_preference"],
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def get_current_user(user_id: str = Depends(current_user_id)) -> User:
    """Authenticate and load the full user row (use only where the profile is needed)."""
    with db_session() as db:
        row = db.execute(
            text("SELECT * FROM users WHERE user_id = :uid"), {"uid": user_id}
        ).fetchone()
    if row is None:
        raise _unauthorized("User no longer exists")
    return row_to_user(row)


def require_same_user(claimed_user_id: str, actual_user_id: str) -> None:
    """403 unless the user_id in a path/body matches the authenticated user."""
    if claimed_user_id != actual_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def require_account(db, user_id: str) -> None:
    """
    401 unless the account still exists. Access tokens are verified without a database lookup and
    outlive an account deletion by up to their 15-minute lifetime, so anything that CREATES rows
    must check — otherwise a deleted account's token keeps adding data nobody can ever remove.
    (401, not 403: the app reads it as "this session is over" and signs the user out.)
    """
    if db.execute(text("SELECT 1 FROM users WHERE user_id = :u"), {"u": user_id}).fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
