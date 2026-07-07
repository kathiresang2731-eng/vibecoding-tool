from __future__ import annotations

from ..context import AppContext
from .telemetry import GenerationPipeline, call_generation_pipeline_with_current_telemetry
from .stream import yield_generation_stream_events
from .worker import start_generation_stream_worker


def generation_stream_events(
  project_id: str,
  prompt: str,
  context: AppContext,
  user: UserContext,
  *,
  model: str | None,
  run_generation_pipeline: GenerationPipeline,
  system_name: str | None = None,
  chat_session_id: str | None = None,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  patch_action: str | None = None,
  model_policy: str | None = None,
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
):
  event_queue, tracker = start_generation_stream_worker(
    run_generation_pipeline=run_generation_pipeline,
    project_id=project_id,
    prompt=prompt,
    context=context,
    user=user,
    model=model,
    system_name=system_name,
    chat_session_id=chat_session_id,
    confirmation_action=confirmation_action,
    attachments=attachments,
    patch_action=patch_action,
    model_policy=model_policy,
    artifact_model=artifact_model,
    request_class=request_class,
    estimated_credit_reservation=estimated_credit_reservation,
  )
  yield from yield_generation_stream_events(event_queue, tracker)
