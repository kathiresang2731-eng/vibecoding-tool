from __future__ import annotations

from typing import Any, Callable

from backend.audit_logging import RunTelemetryContext
from backend.agents.request_complexity import classify_adaptive_request_route
from backend.agents.request_complexity import ADAPTIVE_ROUTE_SMALL_CODE
from backend.agents.project_workspace import meaningful_project_source_files
from backend.agents.chat_history import MAX_STORED_HISTORY_MESSAGES
from backend.agents.runtime_config import streaming_file_agent_enabled
from backend.agents.orchestration.conversation import build_conversation_generation_response, deterministic_conversation_response
from backend.agents.orchestration.state import GenerationPipelineState
from backend.agents.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, GeminiProvider
from backend.code_diff import build_project_diff
from backend.code_diff import redact_project_diff_for_audit
from backend.debug_trace import trace_print
from backend.storage import UserContext
from ..helpers import (
  _list_project_chat_messages_compat,
  _persist_memory_checkpoint_safe,
  _project_workspace_root,
  _record_project_chat_message_compat,
  build_fast_greeting_generation,
  build_gemini_provider,
  default_credit_reservation_for_route,
  generation_model_chat_metadata,
  greeting_fast_path_adk_usage,
  is_simple_greeting_prompt,
  normalize_greeting_lines,
  original_files_for_generated_paths,
  resolve_control_model_for_request,
  resolve_credit_reservation_estimate,
  should_sync_linked_local_folder,
  visible_project_files,
)


def build_generation_project_bundle(
  *,
  context: Any,
  project_id: str,
  prompt: str,
  user: UserContext,
  project: dict[str, Any],
  normalized_attachments: list[dict[str, Any]],
  resolved_chat_session_id: str | None,
  request_class: str | None,
  estimated_credit_reservation: float | int | None,
  model: str | None,
  artifact_model: str | None,
  model_policy: str,
  progress_callback: Callable[[dict[str, Any]], None] | None,
  telemetry: RunTelemetryContext | None,
  system_name: str | None,
  confirmation_action: str | None,
) -> dict[str, Any]:
  original_project_files = context.store.list_files(project_id, user)
  visible_original_project_files = visible_project_files(original_project_files)
  trace_print("EXIT", file=__file__, class_name="-", function="list_project_files", file_count=len(original_project_files), visible_file_count=len(visible_original_project_files))
  adaptive_route = classify_adaptive_request_route(
    prompt,
    project_files=visible_original_project_files,
    attachments=normalized_attachments,
  ).to_dict()
  effective_request_class = str(request_class or adaptive_route.get("route") or "").strip()
  credit_reservation: dict[str, Any] | None = None
  reservation_estimate = resolve_credit_reservation_estimate(effective_request_class, estimated_credit_reservation)
  if (
    reservation_estimate > 0
    and str(getattr(user, "role", "") or "").lower() != "admin"
    and hasattr(context.store, "reserve_ai_credits")
  ):
    credit_reservation = context.store.reserve_ai_credits(
      user.id,
      estimated_credits=reservation_estimate,
      project_id=project_id,
      request_id=telemetry.request_id if telemetry else None,
      route=effective_request_class,
      metadata={
        "model_policy": model_policy,
        "artifact_model": artifact_model,
        "selected_model": model,
      },
    )
    from ..progress import emit_progress
    emit_progress(
      progress_callback,
      "usage.credits.reserved",
      f"Reserved {reservation_estimate:.4f} AI credits for this run",
      status="completed",
      detail={"credit_reservation": credit_reservation},
    )
  from ..progress import emit_progress
  emit_progress(
    progress_callback,
    "routing.adaptive.preflight",
    f"Adaptive preflight selected {str(adaptive_route.get('route') or 'unknown').replace('_', ' ')}",
    status="completed",
    detail=adaptive_route,
  )
  small_code_fast_context = adaptive_route.get("route") == ADAPTIVE_ROUTE_SMALL_CODE
  raw_chat_history = _list_project_chat_messages_compat(
    context.store,
    project_id,
    user,
    limit=MAX_STORED_HISTORY_MESSAGES,
    chat_session_id=resolved_chat_session_id,
  ) if not small_code_fast_context else []
  from backend.agents.chat_history import apply_chat_context_budget, build_current_project_context_contents, build_gemini_chat_history_contents, enrich_website_modification_prompt, latest_enhancement_context, latest_error_context, build_project_path_index_contents, model_chat_history_messages_for_prompt
  raw_chat_history, chat_compaction = apply_chat_context_budget(raw_chat_history) if not small_code_fast_context else ([], {"compacted": False, "total_chars": 0})
  if chat_compaction.get("compacted"):
    emit_progress(
      progress_callback,
      "context.compacted",
      "Compacted chat history to stay within context budget",
      status="completed",
      detail=chat_compaction,
    )
  trace_print("EXIT", file=__file__, class_name="-", function="list_project_chat_messages", message_count=len(raw_chat_history))
  agents_md_block, agents_md_meta = ("", {"bootstrapped": False}) if small_code_fast_context else __import__("backend.agents.memory.agents_md", fromlist=["build_project_agents_md_block"]).build_project_agents_md_block(visible_original_project_files)
  if agents_md_meta.get("bootstrapped"):
    emit_progress(
      progress_callback,
      "agents.md.bootstrapped",
      f"Using default project agent rules for {agents_md_meta.get('path')}",
      status="completed",
      detail=agents_md_meta,
    )
  if small_code_fast_context:
    project_context_contents = []
    emit_progress(
      progress_callback,
      "context.compacted",
      "Using code-only context for standalone code request",
      status="completed",
      detail={"mode": "small_code", "file_count": 0},
    )
  elif streaming_file_agent_enabled():
    project_context_contents = build_project_path_index_contents(visible_original_project_files)
    emit_progress(
      progress_callback,
      "context.compacted",
      "Using path-only project index for fast streaming updates",
      status="completed",
      detail={"mode": "path_index", "file_count": len(visible_original_project_files)},
    )
  else:
    project_context_contents = build_current_project_context_contents(visible_original_project_files)
  model_chat_history = model_chat_history_messages_for_prompt(prompt, raw_chat_history)
  gemini_chat_history = project_context_contents + build_gemini_chat_history_contents(model_chat_history)
  trace_print("EXIT", file=__file__, class_name="-", function="build_gemini_chat_history_contents", content_count=len(gemini_chat_history))
  enhancement_context = latest_enhancement_context(raw_chat_history)
  error_context = latest_error_context(raw_chat_history)
  prompt_for_agents = prompt.strip()
  if not small_code_fast_context and raw_chat_history:
    merged_prompt = enrich_website_modification_prompt(prompt_for_agents, raw_chat_history)
    if merged_prompt != prompt_for_agents:
      emit_progress(
        progress_callback,
        "context.chat_continuity",
        "Merged prior chat session requirements into this request",
        status="completed",
        detail={"prior_message_count": len(raw_chat_history)},
      )
      prompt_for_agents = merged_prompt
  greenfield_project = __import__("backend.agents.project_workspace", fromlist=["is_greenfield_codebase"]).is_greenfield_codebase(visible_original_project_files)
  memory_context = ""
  if not small_code_fast_context:
    from backend.agents.memory.context import build_agent_flow_memory_block
    memory_context = build_agent_flow_memory_block(
      context.store,
      user,
      project_id=project_id,
      prompt=prompt_for_agents,
      chat_session_id=resolved_chat_session_id,
      project_name=str(project.get("name") or ""),
      files=visible_original_project_files,
      chat_messages=raw_chat_history,
      enhancement_context=enhancement_context,
      error_context=error_context,
      ideology_only=greenfield_project,
    )
  if greenfield_project and not small_code_fast_context:
    emit_progress(
      progress_callback,
      "context.greenfield",
      "Greenfield project — no existing code loaded; using platform patterns only",
      status="completed",
      detail={"mode": "ideology_only", "meaningful_file_count": 0},
    )
  workspace_files = [
    str(file_item.get("path") or "").strip()
    for file_item in meaningful_project_source_files(visible_original_project_files)
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip()
  ]
  skills_block = ""
  skill_resolution = None
  return {
    "original_project_files": original_project_files,
    "visible_original_project_files": visible_original_project_files,
    "adaptive_route": adaptive_route,
    "effective_request_class": effective_request_class,
    "credit_reservation": credit_reservation,
    "reservation_estimate": reservation_estimate,
    "small_code_fast_context": small_code_fast_context,
    "raw_chat_history": raw_chat_history,
    "chat_compaction": chat_compaction,
    "agents_md_block": agents_md_block,
    "agents_md_meta": agents_md_meta,
    "project_context_contents": project_context_contents,
    "gemini_chat_history": gemini_chat_history,
    "enhancement_context": enhancement_context,
    "error_context": error_context,
    "prompt_for_agents": prompt_for_agents,
    "greenfield_project": greenfield_project,
    "memory_context": memory_context,
    "workspace_files": workspace_files,
    "skills_block": skills_block,
    "skill_resolution": skill_resolution,
    "project": project,
  }
