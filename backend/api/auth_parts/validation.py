from __future__ import annotations

import re

from fastapi import HTTPException


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def validate_email(email: str) -> str:
  normalized = email.strip().lower()
  if not EMAIL_PATTERN.match(normalized):
    raise HTTPException(status_code=400, detail="Enter a valid email address.")
  return normalized


def validate_password(password: str, *, field_name: str = "Password") -> str:
  if len(password) < MIN_PASSWORD_LENGTH:
    raise HTTPException(status_code=400, detail=f"{field_name} must be at least {MIN_PASSWORD_LENGTH} characters.")
  return password

