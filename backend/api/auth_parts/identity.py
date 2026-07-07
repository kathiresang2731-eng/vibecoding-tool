from __future__ import annotations

from typing import Any

from backend.storage import UserContext


def serialize_user(user: UserContext, *, usage: dict[str, Any] | None = None) -> dict[str, Any]:
  payload = {
    "id": user.id,
    "email": user.email,
    "role": user.role,
    "display_name": user.display_name,
    "is_active": user.is_active,
  }
  if usage is not None:
    payload["usage"] = usage
  return payload
