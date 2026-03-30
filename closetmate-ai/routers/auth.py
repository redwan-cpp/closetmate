from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, EmailStr
import sqlite3

from database import get_db
from models.user import User, UserInDB


router = APIRouter()


class RegisterRequest(BaseModel):
  name: str
  email: EmailStr
  password: str
  gender: str
  body_shape: Optional[str] = None
  skin_tone: Optional[str] = None
  style_preference: Optional[str] = None


class RegisterResponse(BaseModel):
  user_id: str


class LoginRequest(BaseModel):
  email: EmailStr
  password: str


class LoginResponse(BaseModel):
  token: str
  user_id: str


def _row_to_user_in_db(row: sqlite3.Row) -> UserInDB:
  return UserInDB(
    user_id=row["user_id"],
    name=row["name"],
    email=row["email"],
    gender=row["gender"],
    body_shape=row["body_shape"],
    skin_tone=row["skin_tone"],
    style_preference=row["style_preference"],
    created_at=datetime.fromisoformat(row["created_at"]),
    password_hash=row["password_hash"],
  )


def _hash_password(password: str) -> str:
  """Hash a password using bcrypt directly (avoids passlib 1.7.4 / bcrypt 5.x incompatibility)."""
  return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
  return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: sqlite3.Connection = Depends(get_db)) -> RegisterResponse:
  # Check for duplicate email
  existing = db.execute(
    "SELECT user_id FROM users WHERE email = ?",
    (str(payload.email).lower(),),
  ).fetchone()
  if existing:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

  user_id = str(uuid.uuid4())
  created_at = datetime.utcnow().isoformat()
  password_hash = _hash_password(payload.password)

  db.execute(
    """
    INSERT INTO users (
      user_id, name, email, password_hash, gender,
      body_shape, skin_tone, style_preference, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
      user_id,
      payload.name,
      str(payload.email).lower(),
      password_hash,
      payload.gender,
      payload.body_shape,
      payload.skin_tone,
      payload.style_preference,
      created_at,
    ),
  )
  db.commit()

  return RegisterResponse(user_id=user_id)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: sqlite3.Connection = Depends(get_db)) -> LoginResponse:
  row = db.execute(
    "SELECT * FROM users WHERE email = ?",
    (str(payload.email).lower(),),
  ).fetchone()
  if not row:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

  user = _row_to_user_in_db(row)
  if not _verify_password(payload.password, user.password_hash):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

  # Simple dev token: not JWT, not persisted, encodes only user_id.
  token = f"dev-{user.user_id}"
  return LoginResponse(token=token, user_id=user.user_id)


def _parse_token(authorization: Optional[str]) -> str:
  if not authorization:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

  parts = authorization.split()
  if len(parts) != 2 or parts[0].lower() != "bearer":
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header")

  raw = parts[1]
  if not raw.startswith("dev-"):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

  return raw.removeprefix("dev-")


def get_current_user(
  authorization: Optional[str] = Header(default=None, alias="Authorization"),
  db: sqlite3.Connection = Depends(get_db),
) -> User:
  user_id = _parse_token(authorization)
  row = db.execute(
    "SELECT * FROM users WHERE user_id = ?",
    (user_id,),
  ).fetchone()
  if not row:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

  user_db = _row_to_user_in_db(row)
  # Convert to public model (drops password_hash)
  return User(
    user_id=user_db.user_id,
    name=user_db.name,
    email=user_db.email,
    gender=user_db.gender,
    body_shape=user_db.body_shape,
    skin_tone=user_db.skin_tone,
    style_preference=user_db.style_preference,
    created_at=user_db.created_at,
  )


@router.get("/profile", response_model=User)
def profile(current_user: User = Depends(get_current_user)) -> User:
  """
  Return the currently authenticated user's public profile.

  Client must send: Authorization: Bearer dev-<user_id> (from login response).
  """
  return current_user

