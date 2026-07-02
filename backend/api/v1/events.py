from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

V1_EVENT_TYPES: tuple[str, ...] = (
  "run.created",
  "run.progress",
  "run.heartbeat",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "tool.requested",
  "tool.completed",
  "tool.failed",
  "patch.proposed",
  "patch.applied",
  "approval.required",
  "approval.resolved",
  "gate.started",
  "gate.passed",
  "gate.failed",
  "terminal.output",
  "context.search.completed",
)

_LEGACY_TOOL_STEPS = {
  "tool.requested",
  "tool.completed",
  "tool.failed",
}


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


def _map_tool_event(step: str, status: str) -> str | None:
  if step in _LEGACY_TOOL_STEPS:
    return step
  if step.startswith("tool."):
    return step
  if ".tool." in step:
    return "tool.completed" if status == "completed" else "tool.requested"
  return None


def _map_gate_event(step: str, status: str) -> str | None:
  if "validation" in step or "qa" in step or step.startswith("gate."):
    if status == "failed":
      return "gate.failed"
    if status == "completed":
      return "gate.passed"
    return "gate.started"
  return None


def _is_parallel_progress_step(step: str) -> bool:
  if step.startswith(("agent.parallel.", "agent.worker.", "update.analysis.", "orchestrator.wave.")):
    return True
  return step in {
    "context.analysis",
    "update.clarification.required",
    "agent.decision",
  }


def translate_legacy_stream_event(
  legacy: dict[str, Any],
  *,
  run_id: str,
  workspace_id: str,
  client: str,
) -> dict[str, Any]:
  legacy_type = str(legacy.get("type") or "")
  if legacy_type == "complete":
    return make_v1_event(
      "run.completed",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status="completed",
      payload=legacy.get("payload") if isinstance(legacy.get("payload"), dict) else {"result": legacy.get("payload")},
    )

  if legacy_type == "error":
    return make_v1_event(
      "run.failed",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status="failed",
      message=str(legacy.get("user_message") or legacy.get("error") or "Run failed."),
      detail={
        "category": legacy.get("category"),
        "code": legacy.get("code"),
        "status": legacy.get("status"),
        "detail": legacy.get("detail"),
      },
    )

  step = str(legacy.get("step") or "")
  status = str(legacy.get("status") or "running")
  message = str(legacy.get("message") or "")
  detail = legacy.get("detail") if isinstance(legacy.get("detail"), dict) else {}

  if step == "backend.waiting":
    return make_v1_event(
      "run.heartbeat",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status="running",
      message=message or "Run in progress",
      detail=detail,
    )

  tool_type = _map_tool_event(step, status)
  if tool_type:
    return make_v1_event(
      tool_type,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, **detail},
    )

  gate_type = _map_gate_event(step, status)
  if gate_type:
    return make_v1_event(
      gate_type,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, **detail},
    )

  if _is_parallel_progress_step(step):
    return make_v1_event(
      "run.progress",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, "execution_engine": "parallel", **detail},
    )

  if "approval" in step or "confirmation" in step or "brief" in step:
    event_type = "approval.resolved" if status == "completed" else "approval.required"
    return make_v1_event(
      event_type,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, **detail},
    )

  if step in {"patch.proposed", "patch.applied"}:
    return make_v1_event(
      step,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, **detail},
      payload={
        "paths": detail.get("paths") or (detail.get("diff_stats") or {}).get("paths"),
        "diff_stats": detail.get("diff_stats"),
      },
    )

  if step == "file.diff.ready":
    return make_v1_event(
      "patch.proposed",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status="running",
      message=message,
      detail={"step": step, **detail},
      payload={
        "paths": [item.get("path") for item in detail.get("diffs", []) if isinstance(item, dict)],
        "diff_stats": {
          "additions": detail.get("added"),
          "deletions": detail.get("removed"),
          "paths": [item.get("path") for item in detail.get("diffs", []) if isinstance(item, dict)],
        },
      },
    )

  if "patch" in step or "diff" in step or "candidate_code" in step:
    event_type = "patch.applied" if status == "completed" else "patch.proposed"
    return make_v1_event(
      event_type,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status=status,
      message=message,
      detail={"step": step, **detail},
    )

  return make_v1_event(
    "run.progress",
    run_id=run_id,
    workspace_id=workspace_id,
    client=client,
    status=status,
    message=message,
    detail={"step": step, **detail},
  )


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
