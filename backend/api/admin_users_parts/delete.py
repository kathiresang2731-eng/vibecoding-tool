from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

from ..auth import serialize_user


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

