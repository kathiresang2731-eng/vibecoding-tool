from __future__ import annotations

from datetime import datetime, timezone
from queue import Queue
from threading import Thread
from time import monotonic
from typing import Any

from fastapi import HTTPException

try:
  from ...audit_logging import RunTelemetryContext, telemetry_scope
  from ...storage import StorageError, UserContext
except ImportError:
  from audit_logging import RunTelemetryContext, telemetry_scope
  from storage import StorageError, UserContext

from ..errors import storage_http_error
from ..failures import generation_failure_payload
from ..progress import log_runtime_progress_event, make_progress_event
from .telemetry import call_generation_pipeline_with_current_telemetry, GenerationPipeline


def start_generation_stream_worker(
  *,
  run_generation_pipeline: GenerationPipeline,
  project_id: str,
  prompt: str,
  context,
  user: UserContext,
  model: str | None,
  system_name: str | None,
  chat_session_id: str | None,
  confirmation_action: str | None,
  attachments: list[dict[str, Any]] | None,
  patch_action: str | None,
  model_policy: str | None,
  artifact_model: str | None,
  request_class: str | None,
  estimated_credit_reservation: float | int | None,
) -> tuple[Queue[dict[str, Any]], dict[str, Any]]:
  event_queue: Queue[dict[str, Any]] = Queue()
  tracker = {
    "started_at": monotonic(),
    "last_running_step": "backend.starting",
    "last_running_message": "Starting backend pipeline",
  }

  def progress_callback(progress_event: dict[str, Any]) -> None:
    normalized = {
      "status": "running",
      "detail": {},
      "created_at": datetime.now(timezone.utc).isoformat(),
      **progress_event,
    }
    if normalized.get("status") == "running":
      tracker["last_running_step"] = str(normalized.get("step") or tracker["last_running_step"])
      tracker["last_running_message"] = str(normalized.get("message") or tracker["last_running_message"])
    event_queue.put({"type": "progress", **normalized})

  def enrich_and_log_failure(failure: dict[str, Any]) -> dict[str, Any]:
    detail = dict(failure.get("detail") or {})
    if detail.get("elapsed_seconds") in (None, ""):
      detail["elapsed_seconds"] = round(monotonic() - tracker["started_at"], 2)
    if not detail.get("last_runtime_step"):
      detail["last_runtime_step"] = tracker["last_running_step"]
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
  return event_queue, tracker

