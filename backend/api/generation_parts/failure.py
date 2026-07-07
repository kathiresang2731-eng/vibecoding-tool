from __future__ import annotations

from time import monotonic
from typing import Any

from backend.audit_logging import current_telemetry_context, log_query_event
from .flow_trace import log_generation_flow_trace
from backend.agents.memory.topic_clustering import update_chat_topic_after_run
from ..failures import generation_failure_payload
from .helpers import _persist_memory_checkpoint_safe
from ..progress import emit_progress


def report_generation_failure(
  *,
  context: Any,
  user,
  project_id: str,
  project: dict[str, Any] | None,
  prompt: str,
  generation: dict[str, Any] | None,
  progress_callback,
  started_at: float,
  resolved_chat_session_id: str | None,
  provider_label: str,
  provider_model: str,
  credit_reservation: dict[str, Any] | None,
  agent_run: dict[str, Any] | None,
  run: dict[str, Any] | None,
  exc: Exception,
  chat_topic_id: str | None = None,
  topic_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
  failure = generation_failure_payload(exc)
  failure_detail = failure["detail"] | {
    "category": failure["category"],
    "code": failure["code"],
    "elapsed_seconds": round(monotonic() - started_at, 2),
  }
  emit_progress(
    progress_callback,
    "generation.failed",
    failure["user_message"],
    status="failed",
    detail=failure_detail,
  )

  try:
    if isinstance(agent_run, dict):
      context.store.complete_agent_run(agent_run["id"], user, status="failed", error=failure["user_message"])
  except Exception:
    pass

  try:
    if credit_reservation and hasattr(context.store, "complete_ai_credit_reservation"):
      telemetry_context = current_telemetry_context()
      request_id_for_credits = telemetry_context.request_id if telemetry_context else ""
      actual_credits = 0.0
      if hasattr(context.store, "sum_ai_credits_for_request") and request_id_for_credits:
        actual_credits = context.store.sum_ai_credits_for_request(user.id, request_id_for_credits)
      context.store.complete_ai_credit_reservation(
        str(credit_reservation.get("id") or ""),
        actual_credits=actual_credits,
        status="failed",
      )
  except Exception:
    pass

  try:
    if isinstance(agent_run, dict) and resolved_chat_session_id:
      failed_intent = "unknown"
      if isinstance(generation, dict):
        failed_intent = str((generation.get("multi_agent_system") or {}).get("intent") or "unknown")
      _persist_memory_checkpoint_safe(
        context.store,
        user,
        project_id=project_id,
        chat_session_id=resolved_chat_session_id,
        chat_topic_id=chat_topic_id,
        generation_run_id=str(run.get("id") or "") if isinstance(run, dict) else None,
        prompt=prompt,
        intent=failed_intent,
        outcome="failed",
        project_name=str(project.get("name") or "") if isinstance(project, dict) else "",
        error_category=str(failure.get("category") or "generation_failed"),
        extra={"code": failure.get("code"), "chat_topic_id": chat_topic_id, "topic_resolution": topic_resolution or {}},
      )
      update_chat_topic_after_run(
        store=context.store,
        user=user,
        chat_topic_id=chat_topic_id,
        prompt=prompt,
        outcome="failed",
        changed_paths=[],
        metadata={
          "failure_code": failure.get("code"),
          "failure_category": failure.get("category"),
          "agent_run_id": agent_run.get("id") if isinstance(agent_run, dict) else None,
          "topic_resolution": topic_resolution or {},
        },
      )
  except Exception:
    pass

  log_query_event(
    "query.failed",
    status="failed",
    payload=failure,
    provider=provider_label,
    model=provider_model,
    duration_ms=(monotonic() - started_at) * 1000,
  )
  log_generation_flow_trace(
    "conversation.flow.failed",
    prompt=prompt,
    project_id=project_id,
    chat_session_id=resolved_chat_session_id,
    chat_topic_id=chat_topic_id,
    topic_resolution=topic_resolution or {},
    provider=provider_label,
    model=provider_model,
    status="failed",
    extra={"failure": failure},
  )
  return failure
