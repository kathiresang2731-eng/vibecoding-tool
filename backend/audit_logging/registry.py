from __future__ import annotations

from pathlib import Path
from typing import Any

from .logger import StructuredAuditLogger


_AUDIT_LOGGER: StructuredAuditLogger | None = None


def get_audit_logger() -> StructuredAuditLogger:
  global _AUDIT_LOGGER
  if _AUDIT_LOGGER is None:
    _AUDIT_LOGGER = StructuredAuditLogger()
  return _AUDIT_LOGGER


def configure_audit_logger(*, root_dir: str | Path, content_max_chars: int | None = None) -> StructuredAuditLogger:
  global _AUDIT_LOGGER
  _AUDIT_LOGGER = StructuredAuditLogger(root_dir=root_dir, content_max_chars=content_max_chars)
  return _AUDIT_LOGGER


def set_audit_logger_for_tests(logger: StructuredAuditLogger | None) -> None:
  global _AUDIT_LOGGER
  _AUDIT_LOGGER = logger


def log_query_event(event_type: str, **kwargs: Any) -> None:
  get_audit_logger().log_query_event(event_type, **kwargs)


def log_dynamic_agent_event(event_type: str, **kwargs: Any) -> None:
  get_audit_logger().log_dynamic_agent_event(event_type, **kwargs)


def log_flow_event(event_type: str, **kwargs: Any) -> None:
  get_audit_logger().log_flow_event(event_type, **kwargs)
