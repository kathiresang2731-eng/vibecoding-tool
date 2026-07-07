from __future__ import annotations

import json

from fastapi import HTTPException

try:
  from backend.api.run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError
except ImportError:
  from backend.api.run_locks import ProjectGenerationAlreadyRunningError, ProjectGenerationCancelledError


def failure_status_code(exc: Exception, default_status: int) -> int:
  if isinstance(exc, ProjectGenerationAlreadyRunningError):
    return 409
  if isinstance(exc, ProjectGenerationCancelledError):
    return 499
  return default_status


def exception_detail_text(exc: Exception) -> str:
  if isinstance(exc, HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
      return detail
    if isinstance(detail, dict):
      for key in ("user_message", "error", "message", "detail"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
          return value.strip()
      return json.dumps(detail, ensure_ascii=False, default=str)
    return str(detail)
  return str(exc)
