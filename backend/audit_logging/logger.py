from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .constants import DEFAULT_CONTENT_MAX_CHARS, DYNAMIC_AGENT_LOG_NAME, QUERY_LOG_NAME
from .context import RunTelemetryContext, current_telemetry_context
from .sanitize import sanitize_audit_value, strip_candidate_body
from .values import parse_positive_int


class StructuredAuditLogger:
  def __init__(
    self,
    *,
    root_dir: str | Path | None = None,
    content_max_chars: int | None = None,
    now: Callable[[], datetime] | None = None,
  ) -> None:
    self.root_dir = Path(root_dir or os.getenv("AUDIT_LOG_DIR") or "logs").expanduser()
    self.content_max_chars = content_max_chars or parse_positive_int(
      os.getenv("AUDIT_LOG_CONTENT_MAX_CHARS"),
      DEFAULT_CONTENT_MAX_CHARS,
    )
    self.now = now or (lambda: datetime.now(timezone.utc))
    self._lock = threading.Lock()
    self._warned = False

  def log_query_event(
    self,
    event_type: str,
    *,
    status: str = "completed",
    payload: Any = None,
    provider: str | None = None,
    model: str | None = None,
    duration_ms: float | int | None = None,
    context: RunTelemetryContext | None = None,
  ) -> None:
    self._write(
      QUERY_LOG_NAME,
      event_type,
      status=status,
      payload=payload,
      provider=provider,
      model=model,
      duration_ms=duration_ms,
      context=context,
    )

  def log_dynamic_agent_event(
    self,
    event_type: str,
    *,
    status: str = "completed",
    payload: Any = None,
    provider: str | None = None,
    model: str | None = None,
    duration_ms: float | int | None = None,
    context: RunTelemetryContext | None = None,
  ) -> None:
    self._write(
      DYNAMIC_AGENT_LOG_NAME,
      event_type,
      status=status,
      payload=payload,
      provider=provider,
      model=model,
      duration_ms=duration_ms,
      context=context,
    )

  def _write(
    self,
    log_name: str,
    event_type: str,
    *,
    status: str,
    payload: Any,
    provider: str | None,
    model: str | None,
    duration_ms: float | int | None,
    context: RunTelemetryContext | None,
  ) -> None:
    timestamp = self.now().astimezone(timezone.utc)
    telemetry = context or current_telemetry_context()
    if log_name == DYNAMIC_AGENT_LOG_NAME and str(event_type).startswith("candidate_change."):
      payload = strip_candidate_body(payload)
    event = {
      "timestamp": timestamp.isoformat(),
      "request_id": telemetry.request_id if telemetry else None,
      "agent_run_id": telemetry.agent_run_id if telemetry else None,
      "generation_run_id": telemetry.generation_run_id if telemetry else None,
      "user_id": telemetry.user_id if telemetry else None,
      "project_id": telemetry.project_id if telemetry else None,
      "event_type": str(event_type or "unknown"),
      "status": str(status or "completed"),
      "provider": provider,
      "model": model,
      "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
      "payload": sanitize_audit_value(payload, content_max_chars=self.content_max_chars),
    }
    try:
      line = f"{json.dumps(event, ensure_ascii=False, default=str, separators=(',', ':'))}\n".encode("utf-8")
      daily_dir = self.root_dir / timestamp.date().isoformat()
      with self._lock:
        daily_dir.mkdir(parents=True, exist_ok=True)
        file_descriptor = os.open(daily_dir / log_name, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
          os.write(file_descriptor, line)
        finally:
          os.close(file_descriptor)
    except Exception as exc:
      if not self._warned:
        self._warned = True
        print(f"[WorktualAudit] logging unavailable: {str(exc)[:240]}", flush=True)
