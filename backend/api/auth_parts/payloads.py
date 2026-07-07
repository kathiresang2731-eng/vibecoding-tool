from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ...auth import create_access_token, hash_password, verify_password
  from ...config import Settings
  from ...storage import StorageError, UserContext
except ImportError:
  from auth import create_access_token, hash_password, verify_password
  from config import Settings
  from storage import StorageError, UserContext

from ..models import LoginRequest, SignupRequest, UpdateProfileRequest
from .identity import serialize_user
from .validation import validate_email, validate_password


def signup_payload(request: SignupRequest, store, settings: Settings) -> dict[str, Any]:
  if not settings.auth_allow_signup:
    raise HTTPException(
      status_code=403,
      detail="Self-service signup is disabled. Contact your administrator for an account.",
    )
  email = validate_email(request.email)
  password = validate_password(request.password)
  display_name = request.display_name.strip()
  try:
    user = store.create_registered_user(
      email,
      password_hash=hash_password(password),
      display_name=display_name,
      role="owner",
    )
  except StorageError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc
  token = create_access_token(user, settings)
  return {"user": serialize_user(user), "token": token, "authenticated": True}


def login_payload(request: LoginRequest, store, settings: Settings) -> dict[str, Any]:
  email = validate_email(request.email)
  password = validate_password(request.password, field_name="Password")
  record = store.get_user_auth_record_by_email(email)
  if not record or not record.get("password_hash") or not verify_password(password, record.get("password_hash")):
    raise HTTPException(status_code=401, detail="Invalid email or password.")
  if not bool(record.get("is_active", True)):
    raise HTTPException(status_code=403, detail="This account is suspended. Contact your administrator.")
  user = UserContext(
    id=record["id"],
    email=record["email"],
    role=record["role"],
    display_name=record.get("display_name") or "",
    is_active=bool(record.get("is_active", True)),
  )
  token = create_access_token(user, settings)
  usage = store.get_user_usage_summary(user.id)
  return {"user": serialize_user(user, usage=usage), "token": token, "authenticated": True, "usage": usage}


def update_profile_payload(user: UserContext, request: UpdateProfileRequest, store) -> dict[str, Any]:
  password_hash = None
  if request.new_password:
    validate_password(request.new_password, field_name="New password")
    current_password = (request.current_password or "").strip()
    if not current_password:
      raise HTTPException(status_code=400, detail="Current password is required to set a new password.")
    existing_hash = store.get_user_password_hash(user.id)
    if not verify_password(current_password, existing_hash):
      raise HTTPException(status_code=400, detail="Current password is incorrect.")
    password_hash = hash_password(request.new_password)
  elif request.current_password:
    raise HTTPException(status_code=400, detail="Provide a new password to change your password.")

  email = validate_email(request.email) if request.email is not None else None
  display_name = request.display_name.strip() if request.display_name is not None else None
  if email is None and display_name is None and password_hash is None:
    raise HTTPException(status_code=400, detail="No profile changes were provided.")

  try:
    updated = store.update_user_profile(
      user.id,
      email=email,
      display_name=display_name,
      password_hash=password_hash,
    )
  except StorageError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc
  return {"user": serialize_user(updated), "authenticated": True}

