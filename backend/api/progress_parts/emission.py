from __future__ import annotations

from typing import Any, Callable

try:
  from ...audit_logging import log_query_event
  from ...orchestration_terminal import print_orchestration_event, print_user_query
except ImportError:
  from audit_logging import log_query_event
  from orchestration_terminal import print_orchestration_event, print_user_query

from .formatting import compact_terminal_detail, compact_terminal_text, make_progress_event


def log_runtime_progress_event(event: dict[str, Any]) -> None:
  step = str(event.get("step") or "")
  status = str(event.get("status") or "")
  message = str(event.get("message") or "")
  print_orchestration_event(event)
  log_query_event(
    f"runtime.{step or 'progress'}",
    status=status or "running",
    payload={"message": message, "detail": event.get("detail"), "created_at": event.get("created_at")},
  )
  should_log = (
    status == "failed"
    or status == "degraded"
    or ".failed" in step
    or "repair" in step
    or "provider.degraded" == step
  )
  if not should_log:
    return
  detail = event.get("detail")
  detail_text = compact_terminal_detail(detail)
  suffix = f" | {detail_text}" if detail_text else ""
  print(f"[WorktualRuntime] {status.upper()} {step}: {compact_terminal_text(message)}{suffix}", flush=True)


def emit_progress(
  progress_callback: Callable[[dict[str, Any]], None] | None,
  step: str,
  message: str,
  *,
  status: str = "running",
  detail: dict[str, Any] | None = None,
  audit_detail: dict[str, Any] | None = None,
) -> None:
  event = make_progress_event(step, message, status=status, detail=detail)
  audit_event = event if audit_detail is None else {**event, "detail": audit_detail}
  log_runtime_progress_event(audit_event)
  if progress_callback:
    progress_callback(event)

