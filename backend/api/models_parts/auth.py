from __future__ import annotations

from pydantic import BaseModel


class SignupRequest(BaseModel):
  email: str
  password: str
  display_name: str = ""


class LoginRequest(BaseModel):
  email: str
  password: str


class UpdateProfileRequest(BaseModel):
  email: str | None = None
  display_name: str | None = None
  current_password: str | None = None
  new_password: str | None = None

