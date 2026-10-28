"""
routers/auth.py — account lifecycle and profile.

POST   /auth/register   create an account (IP rate-limited)
POST   /auth/login      email + password -> access + refresh tokens
POST   /auth/refresh    rotate the refresh token, get a new access token
POST   /auth/logout     revoke a refresh token
GET    /auth/profile    the signed-in user's profile
PATCH  /auth/profile    update body shape / skin tone
GET    /auth/usage      this month's usage vs. limits (for the app's usage meter)
POST   /auth/delete-account  erase the account and everything it owns (needs the password)

Passwords are bcrypt-hashed. Access tokens are short-lived JWTs; refresh
tokens are opaque, stored hashed, and rotate on every use (see security.py).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database import get_db
from models.profile import normalize_body_shape, normalize_skin_tone
from models.user import User
from quota import usage_summary
from ratelimit import get_limiter, rate_limit_ip, rate_limit_user
from services.photo_store import delete_user_photos
from security import (
    MAX_PASSWORD_BYTES,
    create_access_token,
    current_user_id,
    get_current_user,
    hash_password,
    issue_refresh_token,
    revoke_all_refresh_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
    row_to_user,
    verify_password_or_dummy,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Failed-login lockout: 8 failures per email per 10 minutes (successes don't count).
_LOGIN_FAILURES = get_limiter("login_failures", 8, 600)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    gender: str = Field(min_length=1, max_length=40)
    body_shape: Optional[str] = Field(default=None, max_length=40)
    skin_tone: Optional[str] = Field(default=None, max_length=40)
    style_preference: Optional[str] = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name must not be blank")
        return value

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
        return value

    @field_validator("body_shape")
    @classmethod
    def _body_shape(cls, value: Optional[str]) -> Optional[str]:
        return normalize_body_shape(value)

    @field_validator("skin_tone")
    @classmethod
    def _skin_tone(cls, value: Optional[str]) -> Optional[str]:
        return normalize_skin_tone(value)


class RegisterResponse(BaseModel):
    user_id: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    token: str                      # access token (name kept for existing app builds)
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int                 # access-token lifetime, seconds
    user_id: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    body_shape: Optional[str] = Field(default=None, max_length=40)
    skin_tone: Optional[str] = Field(default=None, max_length=40)

    @field_validator("body_shape")
    @classmethod
    def _body_shape(cls, value: Optional[str]) -> Optional[str]:
        return normalize_body_shape(value)

    @field_validator("skin_tone")
    @classmethod
    def _skin_tone(cls, value: Optional[str]) -> Optional[str]:
        return normalize_skin_tone(value)


def _token_response(db, user_id: str) -> TokenResponse:
    access, expires_in = create_access_token(user_id)
    return TokenResponse(
        token=access,
        refresh_token=issue_refresh_token(db, user_id),
        expires_in=expires_in,
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_ip("register", 10, 3600))],
)
def register(payload: RegisterRequest, db: Any = Depends(get_db)) -> RegisterResponse:
    email = str(payload.email).lower()
    # bcrypt is ~250 ms of CPU: do it before touching the DB so no transaction (or pooler
    # server connection) sits idle-in-transaction while we hash.
    password_hash = hash_password(payload.password)

    existing = db.execute(
        text("SELECT user_id FROM users WHERE email = :email"), {"email": email}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user_id = str(uuid.uuid4())
    try:
        db.execute(
            text("""
                INSERT INTO users (
                    user_id, name, email, password_hash, gender,
                    body_shape, skin_tone, style_preference, created_at
                ) VALUES (:user_id, :name, :email, :password_hash, :gender,
                          :body_shape, :skin_tone, :style_preference, :created_at)
            """),
            {
                "user_id": user_id,
                "name": payload.name.strip(),
                "email": email,
                "password_hash": password_hash,
                "gender": payload.gender,
                "body_shape": payload.body_shape,
                "skin_tone": payload.skin_tone,
                "style_preference": payload.style_preference,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.commit()
    except IntegrityError:
        # Two simultaneous sign-ups with the same email: the unique index decides.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    return RegisterResponse(user_id=user_id)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit_ip("login_ip", 30, 600))],
)
def login(payload: LoginRequest, db: Any = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).lower()

    allowed, retry_after = _LOGIN_FAILURES.peek(email)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "message": "Too many failed attempts. Try again later."},
            headers={"Retry-After": str(retry_after)},
        )

    row = db.execute(text("SELECT * FROM users WHERE email = :email"), {"email": email}).fetchone()
    db.rollback()   # end the read transaction before the slow bcrypt compare (see register)
    # Runs one bcrypt comparison even for unknown emails (no timing oracle).
    if not verify_password_or_dummy(payload.password, row["password_hash"] if row else None):
        _LOGIN_FAILURES.hit(email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    _LOGIN_FAILURES.clear(email)
    response = _token_response(db, row["user_id"])
    db.commit()
    return response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit_ip("refresh", 60, 600))],
)
def refresh(payload: RefreshRequest, db: Any = Depends(get_db)) -> TokenResponse:
    user_id, new_refresh = rotate_refresh_token(db, payload.refresh_token)

    exists = db.execute(
        text("SELECT user_id FROM users WHERE user_id = :u"), {"u": user_id}
    ).fetchone()
    if not exists:
        revoke_all_refresh_tokens(db, user_id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    access, expires_in = create_access_token(user_id)
    return TokenResponse(token=access, refresh_token=new_refresh, expires_in=expires_in, user_id=user_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Any = Depends(get_db)) -> Response:
    revoke_refresh_token(db, payload.refresh_token)   # idempotent
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/profile", response_model=User)
def profile(current_user: User = Depends(get_current_user)) -> User:
    """The signed-in user's public profile (no password hash)."""
    return current_user


@router.patch("/profile", response_model=User)
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
) -> User:
    # Keys come from the pydantic model's own fields, never from the client's JSON.
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return current_user

    set_clause = ", ".join(f"{column} = :{column}" for column in updates)
    db.execute(
        text(f"UPDATE users SET {set_clause} WHERE user_id = :user_id"),
        {"user_id": current_user.user_id, **updates},
    )
    db.commit()

    row = db.execute(
        text("SELECT * FROM users WHERE user_id = :user_id"), {"user_id": current_user.user_id}
    ).fetchone()
    return row_to_user(row)


@router.post(
    "/delete-account",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_user("delete_account", 5, 3600))],
)
def delete_account(
    payload: DeleteAccountRequest,
    user_id: str = Depends(current_user_id),
    db: Any = Depends(get_db),
) -> Response:
    """
    Erase the signed-in user's account and everything it owns: closet, photos, looks, wear
    history, sessions and usage counters. The password is required so a stolen access token
    alone can't do it. This cannot be undone.

    AI usage rows are kept with the user id removed: they are our cost accounting, not the
    user's data. (A wrong password is a 403, not a 401: the app treats 401 as "session expired".)
    """
    row = db.execute(text("SELECT password_hash FROM users WHERE user_id = :u"), {"u": user_id}).fetchone()
    db.rollback()   # end the read transaction before the slow bcrypt compare (see register)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not verify_password_or_dummy(payload.password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Incorrect password")

    # 1. The stored photos FIRST, while the account still exists. If storage is down the user simply
    #    tries again: once the account is gone they could no longer sign in to retry, and the files
    #    would stay behind with nobody able to ask for them to be removed.
    try:
        delete_user_photos(db, user_id)
    except Exception:  # noqa: BLE001
        log.exception("could not remove the stored photos of account %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We couldn't remove your photos just now, so nothing was deleted. Please try again in a moment.",
        )

    # 2. Then the rows, in one transaction: either the account is gone or nothing changed.
    for table in ("refresh_tokens", "saved_looks", "worn_logs", "wardrobe_items", "usage_counters"):
        db.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})   # fixed table names
    db.execute(text("UPDATE ai_usage SET user_id = NULL WHERE user_id = :u"), {"u": user_id})
    db.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": user_id})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usage")
def usage(user_id: str = Depends(current_user_id)) -> Dict[str, Dict[str, int]]:
    """{feature: {used, limit}} for the current calendar month."""
    return usage_summary(user_id)
