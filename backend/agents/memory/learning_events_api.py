from __future__ import annotations

from typing import Any

try:
  from .platform_patterns_api import list_platform_memory_patterns_payload
except ImportError:
  from agents.memory.platform_patterns_api import list_platform_memory_patterns_payload


def serialize_learning_event(row: dict[str, Any]) -> dict[str, Any]:
  metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
  return {
    "id": row.get("id"),
    "user_id": row.get("user_id"),
    "project_id": row.get("project_id"),
    "chat_session_id": row.get("chat_session_id"),
    "run_id": row.get("run_id") or "",
    "request_text_hash": row.get("request_text_hash") or "",
    "normalized_intent": row.get("normalized_intent") or "",
    "domain": row.get("domain") or "general",
    "task_type": row.get("task_type") or "general",
    "changed_paths": row.get("changed_paths_json") or [],
    "validation_status": row.get("validation_status") or "",
    "mistake_type": row.get("mistake_type") or "",
    "extracted_lesson": row.get("extracted_lesson") or "",
    "scope": row.get("scope") or "personal",
    "confidence": float(row.get("confidence") or 0),
    "metadata": metadata,
    "created_at": row.get("created_at"),
  }


def list_learning_events_payload(
  store: Any,
  user: Any,
  *,
  project_id: str | None = None,
  chat_session_id: str | None = None,
  run_id: str | None = None,
  scope: str | None = None,
  limit: int = 50,
  include_all_users: bool = False,
) -> dict[str, Any]:
  if store is None or not hasattr(store, "list_memory_learning_events"):
    return {
      "schema": "worktual.memory-learning-events.v1",
      "events": [],
      "stats": {"listed": 0, "store_available": False},
    }
  rows = store.list_memory_learning_events(
    user,
    project_id=project_id,
    chat_session_id=chat_session_id,
    run_id=run_id,
    scope=scope,
    limit=limit,
    include_all_users=include_all_users,
  )
  events = [serialize_learning_event(row) for row in rows if isinstance(row, dict)]
  return {
    "schema": "worktual.memory-learning-events.v1",
    "events": events,
    "stats": {
      "listed": len(events),
      "store_available": True,
      "include_all_users": bool(include_all_users and getattr(user, "role", "") == "admin"),
    },
  }


def why_injected_payload(
  store: Any,
  user: Any,
  *,
  run_id: str,
  project_id: str | None = None,
  limit: int = 25,
) -> dict[str, Any]:
  event_payload = list_learning_events_payload(
    store,
    user,
    project_id=project_id,
    run_id=run_id,
    limit=limit,
    include_all_users=getattr(user, "role", "") == "admin",
  )
  pattern_payload = list_platform_memory_patterns_payload(store, limit=limit)
  patterns = [
    item
    for item in pattern_payload.get("patterns", [])
    if isinstance(item, dict)
    and (
      str((item.get("metadata") or {}).get("last_evidence_run_id") or "") == str(run_id)
      or str((item.get("metadata") or {}).get("last_applied_run_id") or "") == str(run_id)
    )
  ]
  return {
    "schema": "worktual.memory-why-injected.v1",
    "run_id": run_id,
    "learning_events": event_payload.get("events", []),
    "matching_platform_patterns": patterns,
    "injection_rules": {
      "current_request_overrides_memory": True,
      "one_validated_source": "soft guidance",
      "two_to_four_sources": "recommended pattern",
      "five_or_more_sources": "promoted platform blueprint",
      "failed_or_blocked": "not injected",
    },
  }
