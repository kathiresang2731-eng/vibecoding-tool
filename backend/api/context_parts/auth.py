from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
  from ...auth.tokens import TokenError, decode_access_token
  from ...storage import StorageError, UserContext
except ImportError:
  from auth.tokens import TokenError, decode_access_token
  from storage import StorageError, UserContext

from .bootstrap import AppContext, get_context


_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
  credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
  x_dev_user_email: Optional[str] = Header(default=None),
  context: AppContext = Depends(get_context),
) -> UserContext:
  if credentials and credentials.credentials:
    try:
      payload = decode_access_token(credentials.credentials, context.settings)
      user = context.store.get_user_by_id(str(payload.get("sub") or ""))
      if user:
        return user
    except TokenError as exc:
      raise HTTPException(status_code=401, detail=str(exc)) from exc
    raise HTTPException(status_code=401, detail="Invalid or expired session.")

  if context.settings.auth_allow_dev_header:
    email = x_dev_user_email or context.settings.dev_user_email
    try:
      return context.store.ensure_user(email, role="admin")
    except StorageError as exc:
      raise HTTPException(status_code=503, detail=str(exc)) from exc

  raise HTTPException(status_code=401, detail="Authentication required.")


def require_admin_user(user: UserContext = Depends(get_current_user)) -> UserContext:
  if user.role != "admin":
    raise HTTPException(status_code=403, detail="Admin access required.")
  return user

