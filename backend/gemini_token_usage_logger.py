from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
  from loguru import logger as loguru_logger
except ImportError:  # pragma: no cover - exercised only when optional package is absent.
  loguru_logger = None

try:
  from .audit_logging import RunTelemetryContext, current_telemetry_context
except ImportError:
  from audit_logging import RunTelemetryContext, current_telemetry_context


DEFAULT_TOKEN_USAGE_LOG_DIR = "gemini_token_usage"
TOKEN_USAGE_EXTRA_FLAG = "_worktual_gemini_token_usage"
TOKEN_USAGE_EXTRA_DATE = "_worktual_gemini_token_usage_date"
TOKEN_USAGE_EXTRA_LOGGER_ID = "_worktual_gemini_token_usage_logger_id"


class GeminiTokenUsageLogger:
  def __init__(
    self,
    *,
    root_dir: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
  ) -> None:
    self.root_dir = Path(root_dir or os.getenv("GEMINI_TOKEN_USAGE_LOG_DIR") or DEFAULT_TOKEN_USAGE_LOG_DIR).expanduser()
    self.now = now or (lambda: datetime.now(timezone.utc))
    self._lock = threading.Lock()
    self._sink_ids_by_date: dict[str, int] = {}
    self._warned = False
    self._logger_id = str(uuid.uuid4())

  def log(
    self,
    payload: dict[str, Any],
    *,
    duration_ms: float | int | None = None,
    context: RunTelemetryContext | None = None,
  ) -> None:
    timestamp = self.now().astimezone(timezone.utc)
    telemetry = context or current_telemetry_context()
    event = {
      "timestamp": timestamp.isoformat(),
      "request_id": telemetry.request_id if telemetry else None,
      "agent_run_id": telemetry.agent_run_id if telemetry else None,
      "generation_run_id": telemetry.generation_run_id if telemetry else None,
      "user_id": telemetry.user_id if telemetry else None,
      "project_id": telemetry.project_id if telemetry else None,
      "provider": payload.get("provider") or "gemini",
      "model": payload.get("model"),
      "call": payload.get("call"),
      "input_tokens": payload.get("input_tokens"),
      "output_tokens": payload.get("output_tokens"),
      "total_tokens": payload.get("total_tokens"),
      "thought_tokens": payload.get("thought_tokens"),
      "cached_tokens": payload.get("cached_tokens"),
      "cached_input_tokens": payload.get("cached_input_tokens") or payload.get("cached_tokens"),
      "prompt_chars": payload.get("prompt_chars"),
      "output_chars": payload.get("output_chars"),
      "estimated_cost_usd": payload.get("estimated_cost_usd"),
      "estimated_credits": payload.get("estimated_credits"),
      "pricing_version": payload.get("pricing_version"),
      "route": payload.get("route"),
      "execution_stage": payload.get("execution_stage"),
      "model_role": payload.get("model_role"),
      "thinking_level": payload.get("thinking_level"),
      "context_chars": payload.get("context_chars") or payload.get("prompt_chars"),
      "input_chars": payload.get("input_chars") or payload.get("context_chars") or payload.get("prompt_chars"),
      "system_instruction_chars": payload.get("system_instruction_chars"),
      "chat_history_chars": payload.get("chat_history_chars"),
      "tool_schema_chars": payload.get("tool_schema_chars"),
      "prompt_fragments_used": payload.get("prompt_fragments_used") or [],
      "selected_files": payload.get("selected_files") or [],
      "memory_items_used": payload.get("memory_items_used") or 0,
      "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
    }
    line = json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":"))
    date_key = timestamp.date().isoformat()
    try:
      if loguru_logger is not None:
        self._write_with_loguru(date_key, line)
      else:
        self._write_with_atomic_append(date_key, line)
    except Exception as exc:
      if not self._warned:
        self._warned = True
        print(f"[WorktualTokenUsage] file logging unavailable: {str(exc)[:240]}", flush=True)

  def _write_with_loguru(self, date_key: str, line: str) -> None:
    assert loguru_logger is not None
    self.root_dir.mkdir(parents=True, exist_ok=True)
    with self._lock:
      if date_key not in self._sink_ids_by_date:
        path = self.root_dir / f"{date_key}_token_usage.log"
        sink_id = loguru_logger.add(
          path,
          level="TRACE",
          format="{message}",
          encoding="utf-8",
          mode="a",
          backtrace=False,
          diagnose=False,
          filter=lambda record, expected_date=date_key: (
            record["extra"].get(TOKEN_USAGE_EXTRA_FLAG) is True
            and record["extra"].get(TOKEN_USAGE_EXTRA_DATE) == expected_date
            and record["extra"].get(TOKEN_USAGE_EXTRA_LOGGER_ID) == self._logger_id
          ),
        )
        self._sink_ids_by_date[date_key] = sink_id
    loguru_logger.bind(
      **{
        TOKEN_USAGE_EXTRA_FLAG: True,
        TOKEN_USAGE_EXTRA_DATE: date_key,
        TOKEN_USAGE_EXTRA_LOGGER_ID: self._logger_id,
      }
    ).trace(line)

  def _write_with_atomic_append(self, date_key: str, line: str) -> None:
    path = self.root_dir / f"{date_key}_token_usage.log"
    with self._lock:
      self.root_dir.mkdir(parents=True, exist_ok=True)
      file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
      try:
        os.write(file_descriptor, f"{line}\n".encode("utf-8"))
      finally:
        os.close(file_descriptor)


_GEMINI_TOKEN_USAGE_LOGGER: GeminiTokenUsageLogger | None = None


def get_gemini_token_usage_logger() -> GeminiTokenUsageLogger:
  global _GEMINI_TOKEN_USAGE_LOGGER
  if _GEMINI_TOKEN_USAGE_LOGGER is None:
    _GEMINI_TOKEN_USAGE_LOGGER = GeminiTokenUsageLogger()
  return _GEMINI_TOKEN_USAGE_LOGGER


def configure_gemini_token_usage_logger(*, root_dir: str | Path) -> GeminiTokenUsageLogger:
  global _GEMINI_TOKEN_USAGE_LOGGER
  _GEMINI_TOKEN_USAGE_LOGGER = GeminiTokenUsageLogger(root_dir=root_dir)
  return _GEMINI_TOKEN_USAGE_LOGGER


def set_gemini_token_usage_logger_for_tests(logger: GeminiTokenUsageLogger | None) -> None:
  global _GEMINI_TOKEN_USAGE_LOGGER
  _GEMINI_TOKEN_USAGE_LOGGER = logger


def log_gemini_token_usage(
  payload: dict[str, Any],
  *,
  duration_ms: float | int | None = None,
  context: RunTelemetryContext | None = None,
) -> None:
  get_gemini_token_usage_logger().log(payload, duration_ms=duration_ms, context=context)
  telemetry = context or current_telemetry_context()
  user_id = telemetry.user_id if telemetry else None
  total_tokens = payload.get("total_tokens")
  if total_tokens is None:
    input_tokens = int(payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("output_tokens") or 0)
    total_tokens = input_tokens + output_tokens
  try:
    from .usage.recorder import record_user_token_usage_from_logger
  except ImportError:
    from usage.recorder import record_user_token_usage_from_logger
  record_user_token_usage_from_logger(
    user_id,
    int(total_tokens or 0),
    payload=payload,
    telemetry=telemetry,
    duration_ms=duration_ms,
  )
