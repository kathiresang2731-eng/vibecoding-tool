from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ..auth import hash_password
  from ..storage import StorageError, UserContext
  from .auth import serialize_user, validate_email, validate_password
  from .models import AdminCreateUserRequest, AdminUpdateUserRequest
except ImportError:
  from auth import hash_password
  from storage import StorageError, UserContext
  from api.auth import serialize_user, validate_email, validate_password
  from api.models import AdminCreateUserRequest, AdminUpdateUserRequest


def require_admin_user(user: UserContext) -> None:
  if user.role != "admin":
    raise HTTPException(status_code=403, detail="Admin access required.")


def list_admin_users_payload(store) -> dict[str, Any]:
  return {"users": store.list_managed_users()}


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


def update_admin_user_payload(user_id: str, request: AdminUpdateUserRequest, store, admin: UserContext) -> dict[str, Any]:
  if user_id == admin.id and request.is_active is False:
    raise HTTPException(status_code=400, detail="You cannot suspend your own admin account.")
  account = store.get_user_account_row(user_id)
  if not account:
    raise HTTPException(status_code=404, detail="User not found.")
  if str(account.get("role") or "") == "admin" and request.is_active is False and user_id != admin.id:
    raise HTTPException(status_code=400, detail="Suspending another admin account is not allowed.")

  password_hash = None
  if request.password:
    password_hash = hash_password(validate_password(request.password))
  if request.password and request.display_name is not None and request.display_name.strip() == request.password:
    raise HTTPException(status_code=400, detail="Username cannot be the same as the password.")

  try:
    updated = store.update_user_profile(
      user_id,
      email=validate_email(request.email) if request.email is not None else None,
      display_name=request.display_name.strip() if request.display_name is not None else None,
      password_hash=password_hash,
    )
  except StorageError as exc:
    raise HTTPException(status_code=409, detail=str(exc)) from exc

  if request.is_active is not None:
    store.set_user_active(user_id, is_active=bool(request.is_active))

  extend_requested = any(
    value is not None and int(value) > 0
    for value in (
      request.extend_daily_tokens,
      request.extend_weekly_tokens,
      request.extend_monthly_tokens,
    )
  )
  absolute_requested = any(
    value is not None
    for value in (
      request.daily_token_limit,
      request.weekly_token_limit,
      request.monthly_token_limit,
    )
  )
  credit_requested = request.monthly_ai_credits is not None

  if extend_requested:
    store.extend_user_usage_limits(
      user_id,
      add_daily=int(request.extend_daily_tokens or 0),
      add_weekly=int(request.extend_weekly_tokens or 0),
      add_monthly=int(request.extend_monthly_tokens or 0),
      reset_usage=bool(request.reset_usage),
    )
  elif absolute_requested or request.reset_usage:
    store.update_user_usage_limits(
      user_id,
      daily_token_limit=request.daily_token_limit,
      weekly_token_limit=request.weekly_token_limit,
      monthly_token_limit=request.monthly_token_limit,
      reset_usage=bool(request.reset_usage),
    )
  if credit_requested or request.reset_usage:
    if hasattr(store, "update_user_ai_credit_account"):
      store.update_user_ai_credit_account(
        user_id,
        included_monthly_credits=request.monthly_ai_credits,
        reset_usage=bool(request.reset_usage),
      )

  usage = store.get_user_usage_summary(user_id)
  refreshed = store.get_user_by_id(user_id) or updated
  return {"user": serialize_user(refreshed), "usage": usage}


def delete_admin_user_payload(user_id: str, store, admin: UserContext) -> dict[str, Any]:
  if user_id == admin.id:
    raise HTTPException(status_code=400, detail="You cannot delete your own admin account.")
  account = store.get_user_account_row(user_id)
  if not account:
    raise HTTPException(status_code=404, detail="User not found.")
  if str(account.get("role") or "") == "admin":
    raise HTTPException(status_code=400, detail="Deleting admin accounts is not allowed.")
  store.delete_managed_user(user_id)
  return {"status": "deleted", "user_id": user_id}
