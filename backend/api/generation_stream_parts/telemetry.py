from __future__ import annotations

from inspect import signature
from typing import Any, Callable

GenerationPipeline = Callable[..., dict[str, Any]]


def call_generation_pipeline_with_current_telemetry(
  run_generation_pipeline: GenerationPipeline,
  project_id: str,
  prompt: str,
  context,
  user,
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

