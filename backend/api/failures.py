from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .failures_parts.classification import (
  classify_generation_failure,
  detect_generation_failure_cause,
  exception_detail_text,
  extract_failure_repair_reason,
  extract_last_runtime_step,
  extract_runtime_timeout_seconds,
  failure_cause_label,
  failure_status_code,
  gemini_artifact_failure_marker,
  local_control_failure_marker,
  normalize_generation_model,
  provider_from_failure_category,
  scoped_update_guard_code,
  scoped_update_guard_reason,
  scoped_update_guard_user_message,
)


def generation_failure_payload(exc: Exception, *, default_status: int = 502) -> dict[str, Any]:
  status = exc.status_code if isinstance(exc, HTTPException) else failure_status_code(exc, default_status)
  raw_error = exception_detail_text(exc)
  category, code, user_message = classify_generation_failure(raw_error, exc)
  repair_reason = extract_failure_repair_reason(raw_error)
  runtime_timeout = extract_runtime_timeout_seconds(raw_error)
  try:
    from ..platform.repair_routing import failure_repair_route
  except ImportError:
    from backend.platform.repair_routing import failure_repair_route
  repair_route = failure_repair_route(category=category, code=code, raw_error=raw_error)
  return {
    "status": status,
    "category": category,
    "code": code,
    "error": user_message,
    "user_message": user_message,
    "repair_route": repair_route,
    "detail": {
      "raw_error": raw_error[:2400],
      "exception_type": exc.__class__.__name__,
      "rollback_completed": "restored previous project files" in raw_error.lower(),
      "provider": provider_from_failure_category(category),
      "repair_reason": repair_reason,
      "runtime_timeout_seconds": runtime_timeout,
      "last_runtime_step": extract_last_runtime_step(raw_error),
    },
  }
