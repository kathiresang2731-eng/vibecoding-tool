from __future__ import annotations

from typing import Any, Callable, Iterator

from fastapi import HTTPException

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

from ..context import AppContext
from ..generation_stream import generation_stream_events
from ..progress import ndjson_event
from .events import make_v1_event, new_run_id, translate_legacy_stream_event
from .parsing import _normalize_client


GenerationPipeline = Callable[..., dict[str, Any]]


def v1_runs_stream_events(
  request,
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

