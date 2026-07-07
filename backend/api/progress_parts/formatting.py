from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def make_progress_event(
  step: str,
  message: str,
  *,
  status: str = "running",
  detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
  return {
    "step": step,
    "message": message,
    "status": status,
    "detail": detail or {},
    "created_at": datetime.now(timezone.utc).isoformat(),
  }


def compact_terminal_text(value: str, *, max_chars: int = 700) -> str:
  compacted = " ".join(str(value).split())
  if len(compacted) <= max_chars:
    return compacted
  return f"{compacted[: max_chars - 3]}..."


def compact_terminal_detail(detail: Any, *, max_chars: int = 700) -> str:
  if not isinstance(detail, dict) or not detail:
    return ""
  important = {
    key: detail.get(key)
    for key in (
      "category",
      "code",
      "provider",
      "last_runtime_step",
      "elapsed_seconds",
      "runtime_timeout_seconds",
      "repair_reason",
      "repair_attempt",
      "raw_error",
      "error",
      "reason",
    )
    if detail.get(key) not in (None, "")
  }
  if not important:
    important = detail
  try:
    serialized = json.dumps(important, ensure_ascii=False, default=str)
  except TypeError:
    serialized = str(important)
  return compact_terminal_text(serialized, max_chars=max_chars)


def ndjson_event(payload: dict[str, Any]) -> str:
  return f"{json.dumps(payload, ensure_ascii=False, default=str)}\n"

