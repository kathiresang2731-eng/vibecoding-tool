from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
  from loguru import logger as loguru_logger
except ImportError:  # pragma: no cover
  loguru_logger = None

try:
  from .audit_logging import RunTelemetryContext, current_telemetry_context
except ImportError:
  from audit_logging import RunTelemetryContext, current_telemetry_context


DEFAULT_CONVERSATION_FLOW_LOG_DIR = "logs"
FLOW_EXTRA_FLAG = "_worktual_conversation_flow"
FLOW_EXTRA_DATE = "_worktual_conversation_flow_date"
FLOW_EXTRA_LOGGER_ID = "_worktual_conversation_flow_logger_id"


def _safe_text(value: Any) -> str:
  text = str(value or "").replace("\r", " ").strip()
  return " ".join(text.split())


def _format_paths(label: str, values: list[str]) -> list[str]:
  cleaned = [str(item).strip() for item in values if str(item or "").strip()]
  if not cleaned:
    return [f"{label}: []"]
  return [f"{label}:"] + [f"  - {item}" for item in cleaned]


def _format_mapping(label: str, values: dict[str, list[str] | tuple[str, ...] | str]) -> list[str]:
  if not isinstance(values, dict) or not values:
    return [f"{label}: []"]
  lines = [f"{label}:"]
  for key, raw in values.items():
    name = str(key or "").strip()
    if not name:
      continue
    if isinstance(raw, (list, tuple)):
      cleaned = [str(item).strip() for item in raw if str(item or "").strip()]
    else:
      cleaned = [str(raw).strip()] if str(raw or "").strip() else []
    if not cleaned:
      lines.append(f"  - {name}: []")
      continue
    lines.append(f"  - {name}:")
    lines.extend(f"      * {item}" for item in cleaned)
  return lines if len(lines) > 1 else [f"{label}: []"]


class ConversationFlowLogger:
  def __init__(
    self,
    *,
    root_dir: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
  ) -> None:
    self.root_dir = Path(root_dir or os.getenv("WORKTUAL_TERMINAL_LOG_DIR") or DEFAULT_CONVERSATION_FLOW_LOG_DIR).expanduser()
    self.now = now or (lambda: datetime.now(timezone.utc))
    self._lock = threading.Lock()
    self._sink_ids_by_date: dict[str, int] = {}
    self._warned = False
    self._logger_id = str(uuid.uuid4())

  def log(
    self,
    *,
    event_type: str,
    prompt: str,
    project_id: str,
    chat_session_id: str | None = None,
    chat_topic_id: str | None = None,
    topic_resolution: dict[str, Any] | None = None,
    routing_result: dict[str, Any] | None = None,
    adaptive_route: dict[str, Any] | None = None,
    selected_files: list[str] | None = None,
    generated_files: list[dict[str, Any]] | None = None,
    project_files: list[dict[str, Any]] | None = None,
    status: str = "completed",
    provider: str | None = None,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
    context: RunTelemetryContext | None = None,
  ) -> None:
    timestamp = self.now().astimezone(timezone.utc)
    telemetry = context or current_telemetry_context()
    date_key = timestamp.date().isoformat()
    route = routing_result if isinstance(routing_result, dict) else {}
    topic = topic_resolution if isinstance(topic_resolution, dict) else {}
    adaptive = adaptive_route if isinstance(adaptive_route, dict) else {}
    generated_paths = [
      str(item.get("path") or "").strip()
      for item in (generated_files or [])
      if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    project_paths = [
      str(item.get("path") or "").strip()
      for item in (project_files or [])
      if isinstance(item, dict) and str(item.get("path") or "").strip()
    ][:40]
    lines = [
      "=" * 80,
      f"timestamp: {timestamp.isoformat()}",
      f"event: {event_type}",
      f"status: {status}",
      f"request_id: {_safe_text(telemetry.request_id if telemetry else '')}",
      f"project_id: {_safe_text(project_id)}",
      f"user_id: {_safe_text(telemetry.user_id if telemetry else '')}",
      f"chat_session_id: {_safe_text(chat_session_id)}",
      f"chat_topic_id: {_safe_text(chat_topic_id)}",
      f"provider: {_safe_text(provider)}",
      f"model: {_safe_text(model)}",
      f"prompt: {_safe_text(prompt)}",
    ]
    effective_prompt = _safe_text((extra or {}).get("effective_prompt"))
    if effective_prompt:
      lines.append(f"effective_prompt: {effective_prompt}")
    lines.extend(
      [
        f"topic_action: {_safe_text(topic.get('topic_action'))}",
        f"topic_reason: {_safe_text(topic.get('reason'))}",
        f"topic_confidence: {_safe_text(topic.get('confidence'))}",
        f"adaptive_route: {_safe_text(adaptive.get('route'))}",
        f"adaptive_reason: {_safe_text(adaptive.get('reason'))}",
        f"intent: {_safe_text(route.get('intent') or (extra or {}).get('intent'))}",
        f"next_action: {_safe_text(route.get('next_action'))}",
        f"next_tool: {_safe_text(route.get('next_tool'))}",
        f"route_reason: {_safe_text(route.get('reason') or route.get('routing_reason'))}",
      ]
    )
    lines.extend(_format_paths("selected_files", [str(item) for item in (selected_files or [])]))
    lines.extend(_format_paths("generated_files", generated_paths))
    lines.extend(_format_paths("project_context_files", project_paths))
    if extra:
      backend_flow_files = extra.get("backend_flow_files")
      if isinstance(backend_flow_files, list):
        lines.extend(_format_paths("backend_flow_files", [str(item) for item in backend_flow_files]))
      backend_flow_functions = extra.get("backend_flow_functions")
      if isinstance(backend_flow_functions, dict):
        lines.extend(_format_mapping("backend_flow_functions", backend_flow_functions))
      backend_flow_process = extra.get("backend_flow_process")
      if isinstance(backend_flow_process, list):
        lines.extend(_format_paths("backend_flow_process", [str(item) for item in backend_flow_process]))
      semantic_flow_files = extra.get("semantic_flow_files")
      if isinstance(semantic_flow_files, list):
        lines.extend(_format_paths("semantic_flow_files", [str(item) for item in semantic_flow_files]))
      semantic_flow_functions = extra.get("semantic_flow_functions")
      if isinstance(semantic_flow_functions, dict):
        lines.extend(_format_mapping("semantic_flow_functions", semantic_flow_functions))
      semantic_flow_process = extra.get("semantic_flow_process")
      if isinstance(semantic_flow_process, list):
        lines.extend(_format_paths("semantic_flow_process", [str(item) for item in semantic_flow_process]))
      infra_flow_files = extra.get("infra_flow_files")
      if isinstance(infra_flow_files, list):
        lines.extend(_format_paths("infra_flow_files", [str(item) for item in infra_flow_files]))
      infra_flow_functions = extra.get("infra_flow_functions")
      if isinstance(infra_flow_functions, dict):
        lines.extend(_format_mapping("infra_flow_functions", infra_flow_functions))
      infra_flow_process = extra.get("infra_flow_process")
      if isinstance(infra_flow_process, list):
        lines.extend(_format_paths("infra_flow_process", [str(item) for item in infra_flow_process]))
      runtime_tool_sequence = extra.get("runtime_tool_sequence")
      if isinstance(runtime_tool_sequence, list):
        lines.extend(_format_paths("runtime_tool_sequence", [str(item) for item in runtime_tool_sequence]))
      runtime_steps = extra.get("runtime_steps")
      if isinstance(runtime_steps, list):
        lines.extend(_format_paths("runtime_steps", [str(item) for item in runtime_steps]))
      workspace_candidate_pool = extra.get("workspace_candidate_pool")
      if isinstance(workspace_candidate_pool, list):
        lines.extend(_format_paths("workspace_candidate_pool", [str(item) for item in workspace_candidate_pool]))
      for key in ("chat_history_count", "greenfield_project", "skill_requested", "tool_source_of_truth", "local_sync_error"):
        if key in extra:
          lines.append(f"{key}: {_safe_text(extra.get(key))}")
      if extra.get("failure"):
        lines.append(f"failure: {_safe_text(extra.get('failure'))}")
    text = "\n".join(lines)
    try:
      if loguru_logger is not None:
        self._write_with_loguru(date_key, text)
      else:
        self._write_with_atomic_append(date_key, text)
    except Exception as exc:
      if not self._warned:
        self._warned = True
        print(f"[WorktualConversationFlow] file logging unavailable: {str(exc)[:240]}", flush=True)

  def _write_with_loguru(self, date_key: str, text: str) -> None:
    assert loguru_logger is not None
    self.root_dir.mkdir(parents=True, exist_ok=True)
    with self._lock:
      if date_key not in self._sink_ids_by_date:
        path = self.root_dir / f"teminal_testinh_{date_key}.log"
        sink_id = loguru_logger.add(
          path,
          level="INFO",
          format="{message}",
          encoding="utf-8",
          mode="a",
          backtrace=False,
          diagnose=False,
          filter=lambda record, expected_date=date_key: (
            record["extra"].get(FLOW_EXTRA_FLAG) is True
            and record["extra"].get(FLOW_EXTRA_DATE) == expected_date
            and record["extra"].get(FLOW_EXTRA_LOGGER_ID) == self._logger_id
          ),
        )
        self._sink_ids_by_date[date_key] = sink_id
    loguru_logger.bind(
      **{
        FLOW_EXTRA_FLAG: True,
        FLOW_EXTRA_DATE: date_key,
        FLOW_EXTRA_LOGGER_ID: self._logger_id,
      }
    ).info(text)

  def _write_with_atomic_append(self, date_key: str, text: str) -> None:
    path = self.root_dir / f"teminal_testinh_{date_key}.log"
    with self._lock:
      self.root_dir.mkdir(parents=True, exist_ok=True)
      file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
      try:
        os.write(file_descriptor, f"{text}\n".encode("utf-8"))
      finally:
        os.close(file_descriptor)


_CONVERSATION_FLOW_LOGGER: ConversationFlowLogger | None = None


def get_conversation_flow_logger() -> ConversationFlowLogger:
  global _CONVERSATION_FLOW_LOGGER
  if _CONVERSATION_FLOW_LOGGER is None:
    _CONVERSATION_FLOW_LOGGER = ConversationFlowLogger()
  return _CONVERSATION_FLOW_LOGGER


def set_conversation_flow_logger_for_tests(logger: ConversationFlowLogger | None) -> None:
  global _CONVERSATION_FLOW_LOGGER
  _CONVERSATION_FLOW_LOGGER = logger
