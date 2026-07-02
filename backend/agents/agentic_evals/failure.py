from __future__ import annotations

from typing import Any

from .constants import REQUIRED_FAILURE_FIELDS
from .missing import missing_failure_detail_fields
from .scoring import add_check, summarize_checks
from .values import missing_required_fields, object_value, text_value


def evaluate_failure_payload(payload: dict[str, Any]) -> dict[str, Any]:
  """Score stream/API generation failure payloads for structured, user-safe diagnostics."""

  checks: list[dict[str, Any]] = []
  missing_fields = missing_required_fields(payload, REQUIRED_FAILURE_FIELDS)
  detail = object_value(payload.get("detail"))
  add_check(
    checks,
    name="failure_payload_shape",
    passed=not missing_fields,
    detail="Structured failure payload includes status, category, code, message, and detail.",
    missing=missing_fields,
  )
  add_check(
    checks,
    name="user_safe_error_message",
    passed=bool(text_value(payload.get("user_message"))) and payload.get("user_message") == payload.get("error"),
    detail="The stream error exposes the same clean user-safe message as error/user_message.",
    missing=[] if payload.get("user_message") == payload.get("error") else ["user_message == error"],
  )
  add_check(
    checks,
    name="diagnostic_detail",
    passed=bool(text_value(detail.get("raw_error"))) and bool(text_value(detail.get("provider")) or text_value(payload.get("category"))),
    detail="Diagnostic details retain raw backend cause and provider/category context.",
    missing=missing_failure_detail_fields(payload),
  )
  return summarize_checks(checks)
