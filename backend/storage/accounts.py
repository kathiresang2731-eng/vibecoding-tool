from __future__ import annotations

import os
from typing import Any

from .errors import StorageError
from .ids import new_id
from .roles import READ_ROLES
from .user import UserContext


class AccountStoreMixin:
  def _user_context_from_row(self, row: dict[str, Any]) -> UserContext:
    return UserContext(
      id=row["id"],
      email=row["email"],
      role=row["role"],
      display_name=row.get("display_name") or "",
      is_active=bool(row.get("is_active", True)),
    )

  def get_user_by_id(self, user_id: str) -> UserContext | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select id, email, role, display_name, is_active from users where id = %s",
          (user_id,),
        )
        row = cursor.fetchone()
        return self._user_context_from_row(row) if row else None

  def get_user_auth_record_by_email(self, email: str) -> dict[str, Any] | None:
    normalized_email = email.strip().lower()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select id, email, role, display_name, password_hash, is_active from users where email = %s",
          (normalized_email,),
        )
        return cursor.fetchone()

  def email_exists(self, email: str, *, exclude_user_id: str | None = None) -> bool:
    normalized_email = email.strip().lower()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if exclude_user_id:
          cursor.execute(
            "select 1 from users where email = %s and id <> %s limit 1",
            (normalized_email, exclude_user_id),
          )
        else:
          cursor.execute("select 1 from users where email = %s limit 1", (normalized_email,))
        return cursor.fetchone() is not None

  def create_registered_user(
    self,
    email: str,
    *,
    password_hash: str,
    display_name: str = "",
    role: str = "owner",
    created_by_admin_id: str | None = None,
    monthly_ai_credits: float | int | None = None,
    daily_token_limit: int | None = None,
    weekly_token_limit: int | None = None,
    monthly_token_limit: int | None = None,
  ) -> UserContext:
    normalized_email = email.strip().lower()
    normalized_display_name = display_name.strip()
    if role not in READ_ROLES:
      role = "owner"
    if self.email_exists(normalized_email):
      raise StorageError("An account with this email already exists.")
    user_id = new_id()
    default_daily = int(os.getenv("DEFAULT_DAILY_TOKEN_LIMIT", "500000"))
    default_weekly = int(os.getenv("DEFAULT_WEEKLY_TOKEN_LIMIT", "3000000"))
    default_monthly = int(os.getenv("DEFAULT_MONTHLY_TOKEN_LIMIT", "12000000"))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into users (id, email, role, display_name, password_hash, is_active, created_by_admin_id)
          values (%s, %s, %s, %s, %s, true, %s)
          """,
          (user_id, normalized_email, role, normalized_display_name, password_hash, created_by_admin_id),
        )
        cursor.execute(
          "select id, email, role, display_name, is_active from users where id = %s",
          (user_id,),
        )
        row = cursor.fetchone()
        if not row:
          raise StorageError("Failed to create user account.")
    if role != "admin":
      self.ensure_user_usage_limits(
        user_id,
        daily_token_limit=int(daily_token_limit if daily_token_limit is not None else default_daily),
        weekly_token_limit=int(weekly_token_limit if weekly_token_limit is not None else default_weekly),
        monthly_token_limit=int(monthly_token_limit if monthly_token_limit is not None else default_monthly),
      )
      if hasattr(self, "ensure_user_ai_credit_account"):
        self.ensure_user_ai_credit_account(
          user_id,
          included_monthly_credits=monthly_ai_credits if monthly_ai_credits is not None else 1000,
        )
    return self._user_context_from_row(row)

  def update_user_profile(
    self,
    user_id: str,
    *,
    email: str | None = None,
    display_name: str | None = None,
    password_hash: str | None = None,
  ) -> UserContext:
    updates: list[str] = []
    values: list[Any] = []
    if email is not None:
      normalized_email = email.strip().lower()
      if self.email_exists(normalized_email, exclude_user_id=user_id):
        raise StorageError("An account with this email already exists.")
      updates.append("email = %s")
      values.append(normalized_email)
    if display_name is not None:
      updates.append("display_name = %s")
      values.append(display_name.strip())
    if password_hash is not None:
      updates.append("password_hash = %s")
      values.append(password_hash)
    if not updates:
      user = self.get_user_by_id(user_id)
      if not user:
        raise StorageError("User not found.")
      return user
    values.append(user_id)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"update users set {', '.join(updates)} where id = %s",
          tuple(values),
        )
        cursor.execute(
          "select id, email, role, display_name, is_active from users where id = %s",
          (user_id,),
        )
        row = cursor.fetchone()
        if not row:
          raise StorageError("User not found.")
        return self._user_context_from_row(row)

  def get_user_password_hash(self, user_id: str) -> str | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select password_hash from users where id = %s", (user_id,))
        row = cursor.fetchone()
        return row["password_hash"] if row else None
