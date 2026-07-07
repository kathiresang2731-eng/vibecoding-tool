from __future__ import annotations

from typing import Any


def list_admin_users_payload(store) -> dict[str, Any]:
  return {"users": store.list_managed_users()}

