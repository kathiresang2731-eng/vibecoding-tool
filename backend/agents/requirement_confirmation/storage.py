from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .constants import CONFIRMATION_KEY, CONFIRMATION_NAMESPACE
from ..schema.json_safe import json_dumps_for_persistence

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event


def confirmation_enabled(tool_context: Any, *, project_id: str | None, user: Any) -> bool:
  if not project_id or user is None or tool_context is None:
    return False
  settings = getattr(tool_context, "settings", None)
  store = getattr(tool_context, "store", None)
  return bool(
    getattr(settings, "require_plan_confirmation", False)
    and store is not None
    and hasattr(store, "list_memory_items")
    and hasattr(store, "upsert_memory_item")
  )


def load_confirmation(
  tool_context: Any,
  user: Any,
  *,
  project_id: str,
  statuses: set[str],
) -> dict[str, Any] | None:
  if not confirmation_enabled(tool_context, project_id=project_id, user=user):
    return None
  memories = tool_context.store.list_memory_items(
    user,
    project_id=project_id,
    namespace=CONFIRMATION_NAMESPACE,
    limit=5,
  )
  for memory in memories:
    if not isinstance(memory, dict) or memory.get("key") != CONFIRMATION_KEY:
      continue
    try:
      content = json.loads(str(memory.get("content") or "{}"))
    except json.JSONDecodeError:
      return None
    if not isinstance(content, dict):
      continue
    status = str(content.get("status") or "").strip()
    if not status:
      metadata = memory.get("metadata_json") or memory.get("metadata") or {}
      if isinstance(metadata, dict):
        status = str(metadata.get("status") or "").strip()
    if status in statuses:
      if not content.get("status"):
        content = {**content, "status": status}
      return content
  return None


def load_pending_confirmation(tool_context: Any, user: Any, *, project_id: str) -> dict[str, Any] | None:
  return load_confirmation(
    tool_context,
    user,
    project_id=project_id,
    statuses={"pending"},
  )


def load_retryable_confirmation(tool_context: Any, user: Any, *, project_id: str) -> dict[str, Any] | None:
  return load_confirmation(
    tool_context,
    user,
    project_id=project_id,
    statuses={"pending", "confirmed"},
  )


def persist_pending_confirmation(tool_context: Any, user: Any, *, project_id: str, brief: dict[str, Any]) -> dict[str, Any]:
  pending = {
    **brief,
    "status": "pending",
    "updated_at": datetime.now(timezone.utc).isoformat(),
  }
  tool_context.store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=CONFIRMATION_NAMESPACE,
    key=CONFIRMATION_KEY,
    kind="execution_brief",
    content=json_dumps_for_persistence(pending, context="requirement_confirmation.pending"),
    metadata={
      "status": "pending",
      "operation": pending["operation"],
      "risk_level": pending["risk_level"],
    },
  )
  log_query_event(
    "requirements.confirmation.pending",
    status="completed",
    payload={
      "project_id": project_id,
      "operation": pending["operation"],
      "risk_level": pending["risk_level"],
      "summary": pending["summary"],
    },
  )
  return pending


def resolve_pending_confirmation(
  tool_context: Any,
  user: Any,
  *,
  project_id: str,
  pending: dict[str, Any],
  status: str,
) -> None:
  resolved = {
    **pending,
    "status": status,
    "updated_at": datetime.now(timezone.utc).isoformat(),
  }
  tool_context.store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=CONFIRMATION_NAMESPACE,
    key=CONFIRMATION_KEY,
    kind="execution_brief",
    content=json_dumps_for_persistence(resolved, context="requirement_confirmation.resolved"),
    metadata={
      "status": status,
      "operation": resolved.get("operation"),
      "risk_level": resolved.get("risk_level"),
    },
  )
  log_query_event(
    f"requirements.confirmation.{status}",
    status="completed",
    payload={"project_id": project_id, "operation": resolved.get("operation"), "summary": resolved.get("summary")},
  )
