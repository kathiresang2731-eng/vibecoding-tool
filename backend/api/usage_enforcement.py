from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ..storage import StorageError, UserContext
except ImportError:
  from storage import StorageError, UserContext


def assert_user_can_generate(store: Any, user: UserContext) -> dict[str, Any]:
  if not hasattr(store, "user_usage_allows_generation") or not hasattr(store, "get_user_usage_summary"):
    return {"unlimited": True, "blocked": False}
  allowed, reason = store.user_usage_allows_generation(
    user.id,
    role=getattr(user, "role", "user"),
    is_active=getattr(user, "is_active", True),
  )
  summary = store.get_user_usage_summary(user.id)
  if not allowed:
    status = 403 if "suspended" in reason.lower() else 429
    code = "account_suspended" if status == 403 else "ai_credit_limit_exceeded"
    message = reason or ("Account is suspended. Contact your administrator." if status == 403 else "You have completed your user limit.")
    raise HTTPException(
      status_code=status,
      detail={
        "message": message,
        "user_message": message,
        "code": code,
        "usage": summary,
      },
    )
  return summary
