from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
  """
  Public user model returned to clients (no password_hash).
  """

  user_id: str
  name: str
  email: EmailStr
  gender: str
  body_shape: Optional[str] = None
  skin_tone: Optional[str] = None
  style_preference: Optional[str] = None
  created_at: datetime


class UserInDB(User):
  """
  Internal user representation including stored password hash.
  """

  password_hash: str = Field(repr=False)

