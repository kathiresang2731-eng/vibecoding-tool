from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:
  from ..audit_logging import configure_audit_logger
  from ..auth.tokens import TokenError, decode_access_token
  from ..config import ConfigError, Settings, load_settings
  from ..storage import PostgresStore, StorageError, UserContext
except ImportError:
  from audit_logging import configure_audit_logger
  from auth.tokens import TokenError, decode_access_token
  from config import ConfigError, Settings, load_settings
  from storage import PostgresStore, StorageError, UserContext

@dataclass
class AppContext:
  settings: Settings
  store: PostgresStore


_APP_CONTEXT: Optional[AppContext] = None

def build_app() -> FastAPI:
  cors_settings = load_settings(require_database=False)
  app = FastAPI(title="Vibe Platform Backend", version="1.0.0")
  app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_settings.frontend_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+):517[34]",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-User-Email", "X-Worktual-System-Name", "X-Worktual-Chat-Session-Id"],
  )
  return app


app = build_app()
_bearer_scheme = HTTPBearer(auto_error=False)


def get_context() -> AppContext:
  global _APP_CONTEXT
  if _APP_CONTEXT is None:
    try:
      settings = load_settings(require_database=True)
      audit_log_dir = Path(settings.audit_log_dir).expanduser()
      if not audit_log_dir.is_absolute():
        audit_log_dir = settings.app_root / audit_log_dir
      configure_audit_logger(
        root_dir=audit_log_dir,
        content_max_chars=settings.audit_log_content_max_chars,
      )
      store = PostgresStore(settings.database_url)
      store.bootstrap()
      try:
        from ..usage.recorder import bind_usage_store
      except ImportError:
        from usage.recorder import bind_usage_store
      bind_usage_store(store)
      _APP_CONTEXT = AppContext(settings=settings, store=store)
    except (ConfigError, StorageError) as exc:
      raise HTTPException(status_code=503, detail=str(exc)) from exc
  return _APP_CONTEXT


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
