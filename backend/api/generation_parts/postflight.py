from __future__ import annotations

from time import monotonic
from typing import Any

from backend.audit_logging import current_telemetry_context, log_query_event, update_telemetry_context
from backend.agents.code_index.incremental import maybe_reindex_after_persist
from backend.agents.memory.project_knowledge import persist_project_ui_knowledge
from backend.agents.memory.topic_clustering import update_chat_topic_after_run
from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
from backend.code_diff import build_project_diff, redact_project_diff_for_audit
from backend.debug_trace import trace_print
from backend.storage import UserContext
from .helpers import _persist_memory_checkpoint_safe, _record_project_chat_message_compat, generation_model_chat_metadata
from .status import extract_preview_status_from_generation
from ..local_workspaces import write_linked_project_files
from ..progress import emit_progress


def finalize_generation_success(
  *,
  context: Any,
  user: UserContext,
  project_id: str,
  project: dict[str, Any],
  prompt: str,
  generation: dict[str, Any],
  generated_files: list[dict[str, Any]],
  local_sync: dict[str, Any] | None,
  local_sync_error: str | None,
  provider_label: str,
  provider_model: str,
  progress_callback,
  started_at: float,
  resolved_chat_session_id: str | None,
  model_policy: str,
  artifact_model: str | None,
  effective_request_class: str,
  adaptive_route: dict[str, Any],
  credit_reservation: dict[str, Any] | None,
  reservation_estimate: float,
  agent_run: dict[str, Any],
  run: dict[str, Any] | None,
  persist_agent_runtime_output_fn,
  visible_project_files,
  original_project_files,
  intent: str,
  project_name: str,
  chat_topic_id: str | None = None,
  topic_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
  raise_if_project_run_cancelled = __import__("backend.api.run_locks", fromlist=["raise_if_project_run_cancelled"]).raise_if_project_run_cancelled
  raise_if_project_run_cancelled(None)
  run_label = "generation run" if intent in {"simple_code", "website_generation", "website_update"} else "assistant turn"
  emit_progress(progress_callback, "generation.recording", f"Recording {run_label}")
  run = context.store.create_generation_run(
    project_id,
    user,
    prompt=prompt,
    provider=provider_label,
    status="completed",
    response=generation,
  )
  trace_print("EXIT", file=__file__, class_name="-", function="create_generation_run", run_id=run.get("id"))
  update_telemetry_context(generation_run_id=run["id"])
  emit_progress(
    progress_callback,
    "generation.completed",
    f"{run_label.capitalize()} recorded",
    status="completed",
    detail={"run_id": run["id"]},
  )
  emit_progress(progress_callback, "agent.runtime.persisting", "Persisting agent messages, tool calls, and memory")
  persist_agent_runtime_output_fn(
    context.store,
    agent_run_id=agent_run["id"],
    user=user,
    prompt=prompt,
    generation=generation,
    generation_run=run,
    files=generated_files,
    local_sync=local_sync,
    local_sync_error=local_sync_error,
  )
  trace_print("EXIT", file=__file__, class_name="-", function="persist_agent_runtime_output")
  credit_reservation_result: dict[str, Any] | None = None
  if credit_reservation and hasattr(context.store, "complete_ai_credit_reservation"):
    request_id_for_credits = current_telemetry_context().request_id if current_telemetry_context() else ""
    actual_credits = reservation_estimate
    if hasattr(context.store, "sum_ai_credits_for_request") and request_id_for_credits:
      actual_credits = context.store.sum_ai_credits_for_request(user.id, request_id_for_credits)
    credit_reservation_result = context.store.complete_ai_credit_reservation(
      str(credit_reservation.get("id") or ""),
      actual_credits=actual_credits,
      status="completed",
    )
    emit_progress(
      progress_callback,
      "usage.credits.completed",
      f"Recorded {actual_credits:.4f} actual AI credits for this run",
      status="completed",
      detail={"credit_reservation": credit_reservation_result},
    )
  completed_agent_run = context.store.complete_agent_run(
    agent_run["id"],
    user,
    status="completed",
    output_payload={
      "generation_run_id": run["id"],
      "intent": generation.get("multi_agent_system", {}).get("intent"),
      "file_count": len(generated_files),
      "local_sync": local_sync,
      "local_sync_error": local_sync_error,
      "adaptive_route": adaptive_route,
      "chat_topic_id": chat_topic_id,
      "topic_resolution": topic_resolution or {},
      "model_policy": model_policy,
      "artifact_model": artifact_model,
      "request_class": effective_request_class,
      "credit_reservation": credit_reservation_result or credit_reservation,
    },
    generation_run_id=run["id"],
  )
  if hasattr(context.store, "link_automation_test_runs_to_generation"):
    context.store.link_automation_test_runs_to_generation(
      agent_run_id=str(agent_run["id"]),
      generation_run_id=str(run["id"]),
    )
  trace_print("EXIT", file=__file__, class_name="-", function="complete_agent_run", agent_run_id=completed_agent_run.get("id"))
  intent_value = generation.get("multi_agent_system", {}).get("intent") or "unknown"
  agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime") if isinstance(generation, dict) else {}
  agentic_runtime = agentic_runtime if isinstance(agentic_runtime, dict) else {}
  preview_status = extract_preview_status_from_generation(generation)
  changed_paths = [str(item.get("path") or "") for item in generated_files if isinstance(item, dict)]
  full_project_files = generated_files
  project_knowledge: dict[str, Any] = {"status": "skipped"}
  if intent_value in {"website_generation", "website_update"}:
    try:
      full_project_files = visible_project_files(context.store.list_files(project_id, user))
      project_knowledge = persist_project_ui_knowledge(
        context.store,
        user,
        project_id=project_id,
        files=full_project_files,
        chat_session_id=resolved_chat_session_id,
        chat_topic_id=chat_topic_id,
        generation_run_id=str(run.get("id") or ""),
      )
      emit_progress(
        progress_callback,
        "memory.project_knowledge.updated",
        (
          f"Indexed {int(project_knowledge.get('record_count') or 0)} rendered UI elements "
          f"across {int(project_knowledge.get('file_count') or 0)} source files"
        ),
        status="completed",
        detail={
          "record_count": int(project_knowledge.get("record_count") or 0),
          "file_count": int(project_knowledge.get("file_count") or 0),
          "source_hash": project_knowledge.get("source_hash"),
          "chat_topic_id": chat_topic_id,
        },
      )
    except Exception as exc:
      project_knowledge = {"status": "failed", "error": str(exc)[:500]}
      emit_progress(
        progress_callback,
        "memory.project_knowledge.skipped",
        "Project UI knowledge indexing was skipped; generated files remain saved",
        status="completed",
        detail=project_knowledge,
      )
  runtime_diff = agentic_runtime.get("code_diff_summary") if isinstance(agentic_runtime.get("code_diff_summary"), dict) else {}
  runtime_validation = agentic_runtime.get("validation") if isinstance(agentic_runtime.get("validation"), dict) else {}
  runtime_visual_qa = agentic_runtime.get("visual_qa") if isinstance(agentic_runtime.get("visual_qa"), dict) else {}
  runtime_local_sync = agentic_runtime.get("local_sync") if isinstance(agentic_runtime.get("local_sync"), dict) else {}
  runtime_plan = agentic_runtime.get("work_plan") if isinstance(agentic_runtime.get("work_plan"), dict) else {}
  runtime_contract = (
    runtime_plan.get("coordination_contract")
    if isinstance(runtime_plan.get("coordination_contract"), dict)
    else {}
  )
  orchestration_memory = {
    "workflow": agentic_runtime.get("workflow") or agentic_runtime.get("engine"),
    "worker_protocol": runtime_contract.get("worker_protocol"),
    "worker_count": agentic_runtime.get("worker_count") or runtime_plan.get("worker_count"),
    "task_ids": [
      str(item.get("id"))
      for item in (runtime_plan.get("tasks") or [])
      if isinstance(item, dict) and item.get("id")
    ][:8],
    "route_contract": [
      {
        "route": item.get("route"),
        "file_path": item.get("file_path"),
        "component": item.get("component"),
      }
      for item in (runtime_plan.get("route_contract") or [])
      if isinstance(item, dict)
    ][:20],
    "repair_iterations": int(agentic_runtime.get("repair_iterations") or 0),
    "project_documentation": agentic_runtime.get("project_documentation") or {},
  }
  _persist_memory_checkpoint_safe(
    context.store,
    user,
    project_id=project_id,
    chat_session_id=resolved_chat_session_id,
    chat_topic_id=chat_topic_id,
    generation_run_id=str(run.get("id") or ""),
    prompt=prompt,
    intent=str(intent_value),
    outcome="completed",
    project_name=project_name,
    files=full_project_files,
    changed_paths=changed_paths,
    preview_status=str(preview_status) if preview_status else None,
    extra={
      "generation_run_id": run.get("id"),
      "agent_run_id": completed_agent_run.get("id"),
      "requirement_trace": agentic_runtime.get("requirement_trace") or {},
      "selected_files": (agentic_runtime.get("requirement_trace") or {}).get("selected_files") if isinstance(agentic_runtime.get("requirement_trace"), dict) else [],
      "diff_summary": runtime_diff,
      "validation_status": runtime_validation.get("status"),
      "visual_qa_status": runtime_visual_qa.get("status"),
      "rollback_status": "restored" if agentic_runtime.get("rollback_restored") else "not_required",
      "token_budget_used": agentic_runtime.get("token_budget_used"),
      "route_selected": agentic_runtime.get("branch") or agentic_runtime.get("operation"),
      "route_reason": (agentic_runtime.get("requirement_trace") or {}).get("route_reason") if isinstance(agentic_runtime.get("requirement_trace"), dict) else "",
      "adaptive_route": adaptive_route,
      "chat_topic_id": chat_topic_id,
      "topic_resolution": topic_resolution or {},
      "local_sync_mode": runtime_local_sync.get("mode"),
      "orchestration_memory": orchestration_memory,
      "project_ui_knowledge": {
        "status": project_knowledge.get("status"),
        "record_count": int(project_knowledge.get("record_count") or 0),
        "file_count": int(project_knowledge.get("file_count") or 0),
        "source_hash": project_knowledge.get("source_hash"),
      },
    },
  )
  try:
    update_chat_topic_after_run(
      store=context.store,
      user=user,
      chat_topic_id=chat_topic_id,
      prompt=prompt,
      outcome="completed",
      changed_paths=changed_paths,
      metadata={
        "generation_run_id": run.get("id"),
        "agent_run_id": completed_agent_run.get("id"),
        "intent": intent_value,
        "adaptive_route": adaptive_route,
        "topic_resolution": topic_resolution or {},
        "project_ui_knowledge": {
          "record_count": int(project_knowledge.get("record_count") or 0),
          "source_hash": project_knowledge.get("source_hash"),
        },
      },
    )
  except Exception:
    pass
  if hasattr(context.store, "record_project_chat_message"):
    trace_print("ENTER", file=__file__, class_name="-", function="record_project_chat_message", role="model")
    model_memory, model_metadata = generation_model_chat_metadata(
      generation,
      local_sync=local_sync,
      local_sync_error=local_sync_error,
      base_metadata={
        "source": "generation_api",
        "provider": provider_label,
        "model": provider_model,
        "generation_run_id": run["id"],
        "agent_run_id": completed_agent_run["id"],
        "intent": generation.get("multi_agent_system", {}).get("intent"),
        "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
        "adaptive_route": adaptive_route,
        "chat_topic_id": chat_topic_id,
        "topic_resolution": topic_resolution or {},
        "model_policy": model_policy,
        "artifact_model": artifact_model,
        "request_class": effective_request_class,
        "credit_reservation": credit_reservation_result or credit_reservation,
      },
    )
    _record_project_chat_message_compat(
      context.store,
      project_id,
      user,
      role="model",
      content=model_memory,
      metadata=model_metadata,
      chat_session_id=resolved_chat_session_id,
      chat_topic_id=chat_topic_id,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="record_project_chat_message", role="model")
  emit_progress(
    progress_callback,
    "agent.runtime.persisted",
    "Agent runtime data persisted",
    status="completed",
    detail={"agent_run_id": completed_agent_run["id"]},
  )
  log_query_event(
    "query.completed",
    payload={
      "intent": generation.get("multi_agent_system", {}).get("intent"),
      "file_count": len(generated_files),
      "local_sync": local_sync,
      "adaptive_route": adaptive_route,
      "model_policy": model_policy,
      "artifact_model": artifact_model,
      "request_class": effective_request_class,
      "credit_reservation": credit_reservation_result or credit_reservation,
    },
    provider=provider_label,
    model=provider_model,
    duration_ms=(monotonic() - started_at) * 1000,
  )
  return {
    "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
    "user_id": user.id,
    "chat_session_id": resolved_chat_session_id,
    "chat_topic_id": chat_topic_id,
    "generation_run": run,
    "agent_run": completed_agent_run,
    "generation": generation,
    "files": context.store.list_files(project_id, user),
    "local_sync": local_sync,
    "local_sync_error": local_sync_error,
  }
