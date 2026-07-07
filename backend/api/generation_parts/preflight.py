from __future__ import annotations

from typing import Any, Callable

from backend.audit_logging import RunTelemetryContext
from backend.agents.chat_history import (
  MAX_STORED_HISTORY_MESSAGES,
  apply_chat_context_budget,
  build_current_project_context_contents,
  build_gemini_chat_history_contents,
  enrich_same_topic_referential_prompt,
  model_chat_history_messages_for_prompt,
  enrich_website_modification_prompt,
  recover_update_clarification_prompt,
  latest_enhancement_context,
  latest_error_context,
  build_project_path_index_contents,
)
from backend.agents.memory.context import build_agent_flow_memory_block
from backend.agents.memory.topic_clustering import resolve_chat_topic
from backend.agents.project_workspace import is_greenfield_codebase, meaningful_project_source_files
from backend.agents.project_inspection import asks_with_contextual_reference
from backend.agents.runtime_config import streaming_file_agent_enabled
from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_CONVERSATION,
  ADAPTIVE_ROUTE_SMALL_CODE,
  ADAPTIVE_ROUTE_TINY_CHAT,
  classify_adaptive_request_route,
)
from backend.skills.agents_md import build_project_agents_md_block
from backend.skills.injector import build_skill_recommendation_block, build_skills_prompt_block
from backend.skills.matcher import user_opted_into_skills
from backend.skills.runtime import resolve_skill_request
from ..progress import emit_progress
from .helpers import (
  _list_project_chat_messages_compat,
  _project_workspace_root,
  print_project_workspace_snapshot,
  resolve_credit_reservation_estimate,
  visible_project_files,
)


def prepare_generation_pipeline_inputs(
  *,
  context: Any,
  project_id: str,
  prompt: str,
  user: Any,
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
  topic_llm_provider: Any | None = None,
) -> dict[str, Any]:
  original_project_files = context.store.list_files(project_id, user)
  visible_original_project_files = visible_project_files(original_project_files)
  workspace_snapshot = print_project_workspace_snapshot(
    stage="after_user_input",
    project_id=project_id,
    project=project,
    files=visible_original_project_files,
  )
  emit_progress(
    progress_callback,
    "workspace.files.loaded",
    (
      f"Loaded {workspace_snapshot['input_file_count']} project files from "
      f"{workspace_snapshot['folder']}"
    ),
    status="completed",
    detail=workspace_snapshot,
  )
  adaptive_route = classify_adaptive_request_route(
    prompt,
    project_files=visible_original_project_files,
    attachments=normalized_attachments,
  ).to_dict()
  effective_request_class = str(request_class or adaptive_route.get("route") or "").strip()
  read_only_project_info_context = (
    adaptive_route.get("route") == ADAPTIVE_ROUTE_CONVERSATION
    and adaptive_route.get("use_project_context")
    and not adaptive_route.get("use_parallel_workers")
  )
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
    emit_progress(
      progress_callback,
      "usage.credits.reserved",
      f"Reserved {reservation_estimate:.4f} AI credits for this run",
      status="completed",
      detail={"credit_reservation": credit_reservation},
    )
  emit_progress(
    progress_callback,
    "routing.adaptive.preflight",
    f"Adaptive preflight selected {str(adaptive_route.get('route') or 'unknown').replace('_', ' ')}",
    status="completed",
    detail=adaptive_route,
  )
  small_code_fast_context = adaptive_route.get("route") == ADAPTIVE_ROUTE_SMALL_CODE
  tiny_chat_fast_context = adaptive_route.get("route") == ADAPTIVE_ROUTE_TINY_CHAT
  conversation_fast_context = (
    adaptive_route.get("route") == ADAPTIVE_ROUTE_CONVERSATION
    and not adaptive_route.get("use_project_context")
  )
  minimal_context = small_code_fast_context or tiny_chat_fast_context or conversation_fast_context
  def _emit_topic_progress(step: str, message: str, **kwargs: Any) -> None:
    emit_progress(progress_callback, step, message, **kwargs)

  topic_resolution = resolve_chat_topic(
    store=context.store,
    user=user,
    project_id=project_id,
    chat_session_id=resolved_chat_session_id,
    prompt=prompt,
    project_files=visible_original_project_files,
    adaptive_route=adaptive_route,
    llm_provider=topic_llm_provider,
    emit_progress=_emit_topic_progress,
  )
  chat_topic_id = str(topic_resolution.get("chat_topic_id") or "").strip() or None
  raw_chat_history = _list_project_chat_messages_compat(
    context.store,
    project_id,
    user,
    limit=MAX_STORED_HISTORY_MESSAGES,
    chat_session_id=resolved_chat_session_id,
    chat_topic_id=chat_topic_id,
  ) if not minimal_context else []
  raw_chat_history, chat_compaction = apply_chat_context_budget(raw_chat_history) if not minimal_context else ([], {"compacted": False, "total_chars": 0})
  if chat_compaction.get("compacted"):
    emit_progress(
      progress_callback,
      "context.compacted",
      "Compacted chat history to stay within context budget",
      status="completed",
      detail=chat_compaction,
    )
  agents_md_block, agents_md_meta = ("", {"bootstrapped": False}) if (minimal_context or read_only_project_info_context) else build_project_agents_md_block(visible_original_project_files)
  if agents_md_meta.get("bootstrapped"):
    emit_progress(
      progress_callback,
      "agents.md.bootstrapped",
      f"Using default project agent rules for {agents_md_meta.get('path')}",
      status="completed",
      detail=agents_md_meta,
    )
  if minimal_context:
    project_context_contents = []
    emit_progress(
      progress_callback,
      "context.compacted",
      (
        "Using code-only context for standalone code request"
        if small_code_fast_context
        else "Using greeting-only context for a tiny conversation turn"
        if tiny_chat_fast_context
        else "Using conversation-only context for a read-only user question"
      ),
      status="completed",
      detail={
        "mode": (
          "small_code"
          if small_code_fast_context
          else "tiny_chat"
          if tiny_chat_fast_context
          else "conversation"
        ),
        "file_count": 0,
      },
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
  enhancement_context = latest_enhancement_context(raw_chat_history)
  error_context = latest_error_context(raw_chat_history)
  prompt_for_agents = prompt.strip()
  if not minimal_context and raw_chat_history:
    recovered_prompt = recover_update_clarification_prompt(prompt_for_agents, raw_chat_history)
    if recovered_prompt != prompt_for_agents:
      emit_progress(
        progress_callback,
        "context.update_clarification_resumed",
        "Recovered the pending website update from the latest clarification reply",
        status="completed",
        detail={"source": "chat_session_followup"},
      )
      prompt_for_agents = recovered_prompt
  if not minimal_context and raw_chat_history:
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
  should_apply_referential_followup = (
    not minimal_context
    and raw_chat_history
    and (
      not read_only_project_info_context
      or (
        asks_with_contextual_reference(prompt_for_agents)
        and not any(
          phrase in prompt_for_agents.lower()
          for phrase in (
            "this project",
            "that project",
            "current project",
            "this website",
            "that website",
            "current website",
          )
        )
      )
    )
  )
  if should_apply_referential_followup:
    referential_prompt = enrich_same_topic_referential_prompt(prompt_for_agents, raw_chat_history)
    if referential_prompt != prompt_for_agents:
      emit_progress(
        progress_callback,
        "context.referential_followup",
        "Resolved same-topic follow-up references from recent chat continuity",
        status="completed",
        detail={"prior_message_count": len(raw_chat_history), "source": "chat_topic_followup"},
      )
      prompt_for_agents = referential_prompt
  greenfield_project = is_greenfield_codebase(visible_original_project_files)
  memory_context = ""
  if not minimal_context and not read_only_project_info_context:
    memory_context = build_agent_flow_memory_block(
      context.store,
      user,
      project_id=project_id,
      prompt=prompt_for_agents,
      chat_session_id=resolved_chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=str(project.get("name") or ""),
      files=visible_original_project_files,
      chat_messages=raw_chat_history,
      enhancement_context=enhancement_context,
      error_context=error_context,
      ideology_only=greenfield_project,
    )
  if greenfield_project and not minimal_context and not read_only_project_info_context:
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
  if not minimal_context and not read_only_project_info_context and user_opted_into_skills(prompt):
    skill_resolution = resolve_skill_request(
      prompt,
      workspace_root=_project_workspace_root(project),
      workspace_files=workspace_files,
      project_files=original_project_files,
      system_name=system_name,
      local_path=project.get("local_path"),
    )
    matched_skills = skill_resolution.selected
    skills_block = build_skills_prompt_block(matched_skills)
    if skill_resolution.has_explicit_mismatch:
      skills_block = build_skill_recommendation_block(
        selected_names=skill_resolution.explicit_names,
        rejected=skill_resolution.rejected,
        recommended=skill_resolution.recommended,
        missing_names=skill_resolution.missing_names,
        create_skill_suggestion=skill_resolution.create_skill_suggestion,
        reason=skill_resolution.reason,
      )
    if matched_skills:
      emit_progress(
        progress_callback,
        "skills.matched",
        f"Applied {len(matched_skills)} skill(s): {', '.join(skill.name for skill in matched_skills)}",
        status="completed",
        detail={"skills": [skill.to_dict() for skill in matched_skills]},
      )
    elif skill_resolution.has_explicit_mismatch:
      recommended_names = [skill.name for skill in skill_resolution.recommended]
      emit_progress(
        progress_callback,
        "skills.recommendation",
        (
          f"Selected skill is not relevant. Recommended: {', '.join('/' + name for name in recommended_names)}"
          if recommended_names
          else f"Selected skill is not relevant. Recommend creating a new skill: {skill_resolution.create_skill_suggestion}"
        ),
        status="completed",
        detail={
          "selected": skill_resolution.explicit_names,
          "rejected": [skill.to_dict() for skill in skill_resolution.rejected],
          "missing": skill_resolution.missing_names,
          "recommended": [skill.to_dict() for skill in skill_resolution.recommended],
          "create_skill_suggestion": skill_resolution.create_skill_suggestion,
        },
      )
  effective_prompt = prompt_for_agents.strip()
  if (
    not minimal_context
    and not read_only_project_info_context
    and confirmation_action not in {"confirm", "cancel"}
    and not __import__("backend.agents.requirement_confirmation", fromlist=["looks_like_confirmation_reply"]).looks_like_confirmation_reply(effective_prompt)
  ):
    effective_prompt = __import__("backend.api.generation_parts.helpers", fromlist=["append_orchestrator_context"]).append_orchestrator_context(
      prompt_for_agents,
      error_context=error_context,
      enhancement_context=enhancement_context,
      skills_block=skills_block,
      episodic_context=memory_context,
      agents_md_block=agents_md_block,
    )
  return {
    "original_project_files": original_project_files,
    "visible_original_project_files": visible_original_project_files,
    "adaptive_route": adaptive_route,
    "topic_resolution": topic_resolution,
    "chat_topic_id": chat_topic_id,
    "effective_request_class": effective_request_class,
    "credit_reservation": credit_reservation,
    "reservation_estimate": reservation_estimate,
    "small_code_fast_context": small_code_fast_context,
    "tiny_chat_fast_context": tiny_chat_fast_context,
    "read_only_project_info_context": read_only_project_info_context,
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
    "effective_prompt": effective_prompt,
    "workspace_snapshot": workspace_snapshot,
  }
