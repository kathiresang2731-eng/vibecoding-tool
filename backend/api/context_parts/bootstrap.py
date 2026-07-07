from __future__ import annotations

from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

try:
  from ...audit_logging import configure_audit_logger
  from ...config import ConfigError, Settings, load_settings
  from ...storage import PostgresStore, StorageError
except ImportError:
  from audit_logging import configure_audit_logger
  from config import ConfigError, Settings, load_settings
  from storage import PostgresStore, StorageError


@dataclass
class AppContext:
  settings: Settings
  store: PostgresStore


_APP_CONTEXT: Optional[AppContext] = None


@asynccontextmanager
async def _app_lifespan(fastapi_app: FastAPI):
  context = get_context()
  worker_task = None
  if context.settings.memory_consistency_worker_enabled:
    try:
      from ...agents.memory.consistency_service import (
        start_consistency_worker,
        stop_consistency_worker,
      )
    except ImportError:
      from agents.memory.consistency_service import (
        start_consistency_worker,
        stop_consistency_worker,
      )
    worker_task = start_consistency_worker(
      context.store,
      interval_seconds=context.settings.memory_consistency_interval_seconds,
      batch_size=context.settings.memory_consistency_batch_size,
      lock_timeout_seconds=context.settings.memory_consistency_lock_timeout_seconds,
    )
    fastapi_app.state.memory_consistency_worker = worker_task
  try:
    yield
  finally:
    if worker_task is not None:
      await stop_consistency_worker(worker_task)


def build_app() -> FastAPI:
  cors_settings = load_settings(require_database=False)
  app = FastAPI(title="Vibe Platform Backend", version="1.0.0", lifespan=_app_lifespan)
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
        from ...usage.recorder import bind_usage_store
      except ImportError:
        from usage.recorder import bind_usage_store
      bind_usage_store(store)
      _APP_CONTEXT = AppContext(settings=settings, store=store)
    except (ConfigError, StorageError) as exc:
      raise HTTPException(status_code=503, detail=str(exc)) from exc
  return _APP_CONTEXT
