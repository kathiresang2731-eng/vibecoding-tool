from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ...auth import hash_password
  from ...storage import StorageError, UserContext
except ImportError:
  from auth import hash_password
  from storage import StorageError, UserContext

from ..auth import serialize_user, validate_email, validate_password
from ..models import AdminCreateUserRequest


def create_admin_user_payload(request: AdminCreateUserRequest, store, admin: UserContext) -> dict[str, Any]:
  email = validate_email(request.email)
  password = validate_password(request.password)
  display_name = request.display_name.strip()
  if display_name and display_name == password:
    raise HTTPException(status_code=400, detail="Username cannot be the same as the password.")
  try:
    user = store.create_registered_user(
      email,
      password_hash=hash_password(password),
      display_name=display_name,
      role="owner",
      created_by_admin_id=admin.id,
      monthly_ai_credits=request.monthly_ai_credits,
      daily_token_limit=request.daily_token_limit,
      weekly_token_limit=request.weekly_token_limit,
      monthly_token_limit=request.monthly_token_limit,
    )
  except StorageError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc
  usage = store.get_user_usage_summary(user.id)
  return {
    "user": serialize_user(user),
    "usage": usage,
    "credentials_note": "Share the email and password with the user manually. Passwords are not stored in plain text.",
  }

