from __future__ import annotations

from typing import Any, Callable

from backend.agents.memory.context import build_agent_flow_memory_block
from backend.agents.chat_history import (
  apply_chat_context_budget,
  build_current_project_context_contents,
  build_gemini_chat_history_contents,
  enrich_website_modification_prompt,
  latest_enhancement_context,
  latest_error_context,
  build_project_path_index_contents,
  model_chat_history_messages_for_prompt,
)
from backend.agents.memory.agents_md import build_project_agents_md_block
from backend.agents.project_workspace import is_greenfield_codebase, meaningful_project_source_files
from backend.agents.runtime_config import streaming_file_agent_enabled
from backend.skills.injector import build_skill_recommendation_block, build_skills_prompt_block
from backend.skills.matcher import user_opted_into_skills
from backend.skills.runtime import resolve_skill_request
from ..progress import emit_progress
from ..helpers import _list_project_chat_messages_compat
from backend.storage import UserContext


def build_generation_context_bundle(
  *,
  context: Any,
  project_id: str,
  prompt: str,
  user: UserContext,
  project: dict[str, Any],
  normalized_attachments: list[dict[str, Any]],
  resolved_chat_session_id: str | None,
  progress_callback: Callable[[dict[str, Any]], None] | None,
  visible_original_project_files: list[dict[str, Any]],
  small_code_fast_context: bool,
  system_name: str | None,
  effective_request_class: str,
  workspace_files: list[str],
  original_project_files: list[dict[str, Any]],
) -> dict[str, Any]:
  raw_chat_history = _list_project_chat_messages_compat(
    context.store,
    project_id,
    user,
    limit=100,
    chat_session_id=resolved_chat_session_id,
  ) if not small_code_fast_context else []
  raw_chat_history, chat_compaction = apply_chat_context_budget(raw_chat_history) if not small_code_fast_context else ([], {"compacted": False, "total_chars": 0})
  if chat_compaction.get("compacted"):
    emit_progress(
      progress_callback,
      "context.compacted",
      "Compacted chat history to stay within context budget",
      status="completed",
      detail=chat_compaction,
    )
  agents_md_block, agents_md_meta = ("", {"bootstrapped": False}) if small_code_fast_context else build_project_agents_md_block(visible_original_project_files)
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
  elif streaming_file_agent_enabled():
    project_context_contents = build_project_path_index_contents(visible_original_project_files)
  else:
    project_context_contents = build_current_project_context_contents(visible_original_project_files)
  model_chat_history = model_chat_history_messages_for_prompt(prompt, raw_chat_history)
  gemini_chat_history = project_context_contents + build_gemini_chat_history_contents(model_chat_history)
  enhancement_context = latest_enhancement_context(raw_chat_history)
  error_context = latest_error_context(raw_chat_history)
  prompt_for_agents = prompt.strip()
  if not small_code_fast_context and raw_chat_history:
    merged_prompt = enrich_website_modification_prompt(prompt_for_agents, raw_chat_history)
    if merged_prompt != prompt_for_agents:
      prompt_for_agents = merged_prompt
  greenfield_project = is_greenfield_codebase(visible_original_project_files)
  memory_context = ""
  if not small_code_fast_context:
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
  skills_block = ""
  skill_resolution = None
  if not small_code_fast_context and user_opted_into_skills(prompt):
    skill_resolution = resolve_skill_request(
      prompt,
      workspace_root=None,
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
  if raw_chat_history and not small_code_fast_context:
    prompt_for_agents = enrich_website_modification_prompt(prompt_for_agents, raw_chat_history)
  return {
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
    "skills_block": skills_block,
    "skill_resolution": skill_resolution,
  }
