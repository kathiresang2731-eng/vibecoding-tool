from __future__ import annotations

from typing import Any, Callable

from ..context import AppContext
from ..run_locks import acquire_project_run_lock, raise_if_project_run_cancelled

try:
  from ...audit_logging import RunTelemetryContext, telemetry_scope
except ImportError:
  from audit_logging import RunTelemetryContext, telemetry_scope

try:
  from ...runtime_control import runtime_cancellation_scope
except ImportError:
  from runtime_control import runtime_cancellation_scope


def run_generation_resume(
  project_id: str,
  prompt: str,
  context: AppContext,
  user,
  *,
  thread_id: str | None = None,
  model: str | None = None,
  model_policy: str = "auto_staged",
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
  resume_graph: bool = False,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  chat_session_id: str | None = None,
  _telemetry_initialized: bool = False,
) -> dict[str, Any]:
  if not _telemetry_initialized:
    telemetry = RunTelemetryContext.create(user_id=user.id, project_id=project_id)
    with telemetry_scope(telemetry):
      return run_generation_resume(
        project_id,
        prompt,
        context,
        user,
        thread_id=thread_id,
        model=model,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
        resume_graph=resume_graph,
        progress_callback=progress_callback,
        chat_session_id=chat_session_id,
        _telemetry_initialized=True,
      )

  from backend.agents.graph_runtime.threading import parse_runtime_thread_id

  resolved_thread_id = str(thread_id or "").strip()
  if resolved_thread_id:
    parsed_project_id, agent_run_id = parse_runtime_thread_id(resolved_thread_id)
    if parsed_project_id != project_id:
      raise ValueError("thread_id project_id does not match the requested project.")
  else:
    agent_run_id = None

  with acquire_project_run_lock(project_id, user_id=getattr(user, "id", "")) as active_run:
    with runtime_cancellation_scope(lambda: raise_if_project_run_cancelled(active_run)):
      from ..generation import _run_generation_pipeline_unlocked

      return _run_generation_pipeline_unlocked(
        project_id,
        prompt,
        context,
        user,
        model=model,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
        progress_callback=progress_callback,
        active_run=active_run,
        agent_run_id=agent_run_id,
        graph_thread_id=resolved_thread_id or None,
        resume_graph=resume_graph,
        chat_session_id=chat_session_id,
      )
