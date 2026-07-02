from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any, Callable

from fastapi import HTTPException

try:
  from ..audit_logging import RunTelemetryContext, telemetry_scope
  from ..storage import StorageError, UserContext
except ImportError:
  from audit_logging import RunTelemetryContext, telemetry_scope
  from storage import StorageError, UserContext

from .constants import GENERATION_STREAM_HEARTBEAT_SECONDS
from .context import AppContext
from .errors import storage_http_error
from .failures import generation_failure_payload
from .progress import log_runtime_progress_event, make_progress_event, ndjson_event


GenerationPipeline = Callable[..., dict[str, Any]]


def call_generation_pipeline_with_current_telemetry(
  run_generation_pipeline: GenerationPipeline,
  project_id: str,
  prompt: str,
  context: AppContext,
  user: UserContext,
  *,
  model: str | None = None,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  system_name: str | None = None,
  chat_session_id: str | None = None,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  patch_action: str | None = None,
  model_policy: str | None = None,
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
) -> dict[str, Any]:
  kwargs: dict[str, Any] = {"progress_callback": progress_callback}
  if model:
    kwargs["model"] = model
  if system_name:
    kwargs["system_name"] = system_name
  if chat_session_id:
    kwargs["chat_session_id"] = chat_session_id
  if confirmation_action in {"confirm", "cancel"}:
    kwargs["confirmation_action"] = confirmation_action
  if patch_action in {"approve", "reject"}:
    kwargs["patch_action"] = patch_action
  if attachments:
    kwargs["attachments"] = attachments
  if model_policy:
    kwargs["model_policy"] = model_policy
  if artifact_model:
    kwargs["artifact_model"] = artifact_model
  if request_class:
    kwargs["request_class"] = request_class
  if estimated_credit_reservation is not None:
    kwargs["estimated_credit_reservation"] = estimated_credit_reservation
  if "_telemetry_initialized" in signature(run_generation_pipeline).parameters:
    kwargs["_telemetry_initialized"] = True
  return run_generation_pipeline(project_id, prompt, context, user, **kwargs)


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
  event_queue: Queue[dict[str, Any]] = Queue()
  started_at = monotonic()
  last_running_step = "backend.starting"
  last_running_message = "Starting backend pipeline"

  def progress_callback(progress_event: dict[str, Any]) -> None:
    nonlocal last_running_step, last_running_message
    normalized = {
      "status": "running",
      "detail": {},
      "created_at": datetime.now(timezone.utc).isoformat(),
      **progress_event,
    }
    if normalized.get("status") == "running":
      last_running_step = str(normalized.get("step") or last_running_step)
      last_running_message = str(normalized.get("message") or last_running_message)
    event_queue.put({"type": "progress", **normalized})

  def enrich_and_log_failure(failure: dict[str, Any]) -> dict[str, Any]:
    detail = dict(failure.get("detail") or {})
    if detail.get("elapsed_seconds") in (None, ""):
      detail["elapsed_seconds"] = round(monotonic() - started_at, 2)
    if not detail.get("last_runtime_step"):
      detail["last_runtime_step"] = last_running_step
    failure["detail"] = detail
    log_runtime_progress_event(
      make_progress_event(
        "generation.failed",
        str(failure.get("user_message") or failure.get("error") or "Generation failed."),
        status="failed",
        detail=detail | {"category": failure.get("category"), "code": failure.get("code")},
      )
    )
    return failure

  def worker() -> None:
    telemetry = RunTelemetryContext.create(user_id=user.id, project_id=project_id)
    with telemetry_scope(telemetry):
      try:
        payload = call_generation_pipeline_with_current_telemetry(
          run_generation_pipeline,
          project_id,
          prompt,
          context,
          user,
          model=model,
          progress_callback=progress_callback,
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
        event_queue.put({"type": "complete", "payload": payload})
      except HTTPException as exc:
        event_queue.put({"type": "error", **enrich_and_log_failure(generation_failure_payload(exc, default_status=exc.status_code))})
      except StorageError as exc:
        failure = generation_failure_payload(exc, default_status=storage_http_error(exc).status_code)
        event_queue.put({"type": "error", **enrich_and_log_failure(failure)})
      except Exception as exc:
        failure = enrich_and_log_failure(generation_failure_payload(exc))
        try:
          context.store.create_generation_run(
            project_id,
            user,
            prompt=prompt,
            provider=model or "gemini",
            status="failed",
            error=failure["user_message"],
          )
        except Exception:
          pass
        event_queue.put({"type": "error", **failure})
      finally:
        event_queue.put({"type": "end"})

  Thread(target=worker, daemon=True).start()

  while True:
    try:
      event = event_queue.get(timeout=GENERATION_STREAM_HEARTBEAT_SECONDS)
    except Empty:
      yield ndjson_event(
        {
          "type": "progress",
          **make_progress_event(
            "backend.waiting",
            last_running_message,
            detail={"elapsed_seconds": round(monotonic() - started_at)},
          ),
        }
      )
      continue

    if event["type"] == "end":
      break
    if event["type"] == "progress" and event.get("status") == "running":
      last_running_step = str(event.get("step") or last_running_step)
      last_running_message = str(event.get("message") or last_running_message)
    yield ndjson_event(event)
