from __future__ import annotations

from typing import Any, Callable, Iterator

from fastapi import HTTPException

try:
  from ...storage import StorageError, UserContext
except ImportError:
  from storage import StorageError, UserContext

from ..context import AppContext
from ..errors import storage_http_error
from ..generation_stream import generation_stream_events
from ..progress import ndjson_event
from ..run_locks import active_project_run, cancel_project_run
from .events import make_v1_event, new_run_id, translate_legacy_stream_event
from .models import CreateRunRequest


GenerationPipeline = Callable[..., dict[str, Any]]


def _normalize_client(client: str | None) -> str:
  normalized = str(client or "web").strip().lower()
  if normalized in {"web", "cli", "ide"}:
    return normalized
  return "web"


def v1_runs_stream_events(
  request: CreateRunRequest,
  context: AppContext,
  user: UserContext,
  *,
  run_generation_pipeline: GenerationPipeline,
  system_name: str | None = None,
) -> Iterator[str]:
  workspace_id = request.workspace_id.strip()
  prompt = request.prompt.strip()
  if not workspace_id:
    raise HTTPException(status_code=400, detail="workspace_id is required.")
  if not prompt:
    raise HTTPException(status_code=400, detail="prompt is required.")

  client = _normalize_client(request.client)
  run_id = new_run_id()

  yield ndjson_event(
    make_v1_event(
      "run.created",
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
      status="running",
      message="Run accepted by harness.",
      detail={
        "session_id": request.session_id,
        "model": request.model,
        "legacy_project_id": workspace_id,
      },
    )
  )

  for legacy_line in generation_stream_events(
    workspace_id,
    prompt,
    context,
    user,
    model=request.model,
    run_generation_pipeline=run_generation_pipeline,
    system_name=system_name,
  ):
    legacy_payload = _parse_ndjson_line(legacy_line)
    if not legacy_payload:
      continue
    v1_payload = translate_legacy_stream_event(
      legacy_payload,
      run_id=run_id,
      workspace_id=workspace_id,
      client=client,
    )
    yield ndjson_event(v1_payload)


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


def _parse_ndjson_line(line: str) -> dict[str, Any] | None:
  import json

  text = str(line or "").strip()
  if not text:
    return None
  try:
    payload = json.loads(text)
  except json.JSONDecodeError:
    return None
  return payload if isinstance(payload, dict) else None
