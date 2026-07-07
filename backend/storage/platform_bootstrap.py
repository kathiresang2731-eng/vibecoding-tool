from __future__ import annotations

import os
from typing import Any

try:
  from ..auth import hash_password
except ImportError:
  from auth import hash_password

from .errors import StorageError
from .ids import new_id


def _env_bool(key: str, *, default: bool = False) -> bool:
  raw = os.getenv(key, "")
  if not raw.strip():
    return default
  return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_limits() -> tuple[int, int, int]:
  daily = int(os.getenv("DEFAULT_DAILY_TOKEN_LIMIT", "500000"))
  weekly = int(os.getenv("DEFAULT_WEEKLY_TOKEN_LIMIT", "3000000"))
  monthly = int(os.getenv("DEFAULT_MONTHLY_TOKEN_LIMIT", "12000000"))
  return daily, weekly, monthly


def run_platform_bootstrap_extras(store: Any) -> None:
  if _env_bool("PLATFORM_RESET_USERS"):
    with store.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("truncate table users cascade")

  admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
  admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
  admin_display_name = os.getenv("ADMIN_DISPLAY_NAME", "Platform Admin").strip() or "Platform Admin"
  if not admin_email or not admin_password:
    return

  existing = store.get_user_auth_record_by_email(admin_email)
  if existing:
    if str(existing.get("role") or "") != "admin":
      with store.connect() as conn:
        with conn.cursor() as cursor:
          cursor.execute("update users set role = 'admin', is_active = true where id = %s", (existing["id"],))
    return

  user_id = new_id()
  daily, weekly, monthly = _default_limits()
  with store.connect() as conn:
    with conn.cursor() as cursor:
      cursor.execute(
        """
        insert into users (id, email, role, display_name, password_hash, is_active)
        values (%s, %s, 'admin', %s, %s, true)
        """,
        (user_id, admin_email, admin_display_name, hash_password(admin_password)),
      )
  store.ensure_user_usage_limits(
    user_id,
    daily_token_limit=daily,
    weekly_token_limit=weekly,
    monthly_token_limit=monthly,
  )
