from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .constants import V1_EVENT_TYPES


def _utc_now() -> str:
  return datetime.now(timezone.utc).isoformat()


def make_v1_event(
  event_type: str,
  *,
  run_id: str,
  workspace_id: str,
  client: str,
  status: str = "running",
  message: str = "",
  detail: dict[str, Any] | None = None,
  payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
  event: dict[str, Any] = {
    "schema": "worktual.run-event.v1",
    "type": event_type,
    "run_id": run_id,
    "workspace_id": workspace_id,
    "client": client,
    "status": status,
    "created_at": _utc_now(),
  }
  if message:
    event["message"] = message
  if detail:
    event["detail"] = detail
  if payload is not None:
    event["payload"] = payload
  return event


def new_run_id() -> str:
  return uuid4().hex


def event_schema_payload() -> dict[str, Any]:
  return {
    "schema": "worktual.run-event.v1",
    "event_types": list(V1_EVENT_TYPES),
    "clients": ["web", "cli", "ide"],
    "notes": [
      "workspace_id maps to project_id during Phase 0 compatibility.",
      "Legacy /api/projects/{id}/generate-stream events are bridged into this schema.",
    ],
  }
