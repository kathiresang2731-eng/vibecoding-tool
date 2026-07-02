from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

try:
  from ..config import Settings
  from ..storage import UserContext
except ImportError:
  from config import Settings
  from storage import UserContext


class TokenError(ValueError):
  pass


def create_access_token(user: UserContext, settings: Settings) -> str:
  expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.auth_token_ttl_hours)
  payload = {
    "sub": user.id,
    "email": user.email,
    "display_name": user.display_name,
    "role": user.role,
    "exp": expires_at,
  }
  return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
  try:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
  except jwt.PyJWTError as exc:
    raise TokenError("Invalid or expired session.") from exc
  user_id = str(payload.get("sub") or "").strip()
  if not user_id:
    raise TokenError("Invalid session token.")
  return payload
