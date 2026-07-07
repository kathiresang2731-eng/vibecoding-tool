from __future__ import annotations

import json
from typing import Any

try:
  from backend.audit_logging import log_query_event
  from backend.orchestration_terminal import orchestration_terminal_verbose_enabled
except ImportError:
  from audit_logging import log_query_event
  from orchestration_terminal import orchestration_terminal_verbose_enabled

from ..constants import TOOL_LOG_MAX_CHARS


def log_tool_call(tool_name: str, phase: str, payload: Any) -> None:
  try:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
  except TypeError:
    serialized = str(payload)

  if len(serialized) > TOOL_LOG_MAX_CHARS:
    serialized = f"{serialized[:TOOL_LOG_MAX_CHARS]}... <truncated>"

  log_query_event(
    f"tool_route.{phase}",
    status="failed" if "fail" in phase else "completed",
    payload={"tool_name": tool_name, "phase": phase, "payload": payload},
  )
  if orchestration_terminal_verbose_enabled():
    print(f"[WorktualToolCall] {tool_name}.{phase}: {serialized}", flush=True)
