from __future__ import annotations

from typing import Any

from fastapi import HTTPException

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

from ..events import make_v1_event
from ..run_locks import active_project_run, cancel_project_run


def cancel_v1_run(request_workspace_id: str, user: UserContext, *, run_id: str | None = None) -> dict[str, Any]:
  workspace_id = request_workspace_id.strip()
  if not workspace_id:
    raise HTTPException(status_code=400, detail="workspace_id is required.")

  cancelled = cancel_project_run(
    workspace_id,
    user_id=user.id,
    wait_seconds=0.5,
  )
  if not cancelled:
    active = active_project_run(workspace_id, user_id=user.id)
    return {
      "cancelled": False,
      "cancel_requested": False,
      "stopped": active is None,
      "workspace_id": workspace_id,
      "run_id": run_id,
      "active_run": active,
    }

  stopped = bool(cancelled.get("stopped"))
  return {
    "cancelled": True,
    "cancel_requested": True,
    "stopped": stopped,
    "workspace_id": workspace_id,
    "run_id": run_id or cancelled.get("run_id"),
    "active_run": cancelled,
    "event": make_v1_event(
      "run.cancelled",
      run_id=str(cancelled.get("run_id") or run_id or ""),
      workspace_id=workspace_id,
      client="web",
      status="cancelled" if stopped else "cancelling",
      message="Run stopped." if stopped else "Run cancellation requested; waiting for the active operation to exit.",
    ),
  }

