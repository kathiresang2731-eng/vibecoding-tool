from __future__ import annotations

import re
from typing import Any

try:
  from backend.debug_trace import trace_function
except ImportError:
  from debug_trace import trace_function

from backend.agents.prompt_context import current_user_prompt
from backend.agents.prompts import build_scoped_update_patch_prompt
from backend.agents.agent_runtime.errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from backend.agents.agent_runtime.fallbacks import is_artifact_json_invalid_error, is_model_connection_error
from backend.agents.agent_runtime.model_agents import run_artifact_provider_with_soft_timeout
from backend.agents.agent_runtime.schemas import SCOPED_UPDATE_RESPONSE_SCHEMA
from backend.agents.agent_runtime.values import string_list, text_or_default
from backend.agents.agent_runtime.scoped_update.generation import (
  deterministic_onboarding_chat_update_changes,
  deterministic_undefined_name_runtime_fix_changes,
  deterministic_undefined_reference_fix_changes,
)
from backend.agents.agent_runtime.scoped_update.prompting import (
  build_scoped_edit_plan,
  empty_scoped_update_retry_prompt,
  log_scoped_no_patch_response,
  strict_scoped_update_retry_prompt,
  no_effective_scoped_update_retry_prompt,
)
from backend.agents.agent_runtime.scoped_update.runtime_parts.policy import (
  SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP,
  SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_SYSTEM_INSTRUCTION,
  prioritize_scoped_candidate_paths,
  scoped_update_call_timeout_seconds,
  scoped_update_model_error,
)
from backend.agents.agent_runtime.scoped_update.response_parts import normalize_scoped_update_response, should_retry_empty_scoped_update_response
from backend.agents.agent_runtime.scoped_update.task_parts import invalid_scoped_update_json_guard_error


@trace_function(candidate_count=lambda _artifact_provider, **kwargs: len((kwargs.get("update_analysis") or {}).get("candidate_files") or []), previous_error=lambda _artifact_provider, **kwargs: "yes" if kwargs.get("previous_error") else "no")
def run_scoped_update_agent(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None = None,
  deadline_monotonic: float | None = None,
) -> dict[str, Any]:
  prompt = current_user_prompt(prompt)
  existing_by_path = {file_item["path"]: file_item["content"] for file_item in existing_files}
  candidate_paths = [
    path
    for path in string_list(update_analysis.get("candidate_files"), [])
    if path in existing_by_path
  ]
  candidate_paths = prioritize_scoped_candidate_paths(
    candidate_paths,
    prompt=prompt,
    update_analysis=update_analysis,
    existing_by_path=existing_by_path,
  )[:SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP]
  if not candidate_paths:
    raise UpdateRequestNeedsClarificationError(
      "Update request needs clarification before editing files: "
      "I could not identify a safe existing source file for this update. Please name the component or file to change."
    )
  candidate_files: list[dict[str, Any]] = []
  for path in candidate_paths:
    content = existing_by_path[path]
    if len(content) > 160000:
      raise ScopedUpdateGuardError(
        f"Scoped update blocked because {path} is too large for a safe model patch. "
        "Split the component or identify a smaller target first."
      )
    candidate_files.append({"path": path, "content": content, "content_chars": len(content)})
  effective_prompt = prompt
  if previous_error:
    effective_prompt = (
      f"{prompt}\n\n"
      "The previous scoped patch failed validation or preview QA:\n"
      f"{previous_error[:2400]}\n\n"
      "Retry as a minimal existing-code patch. If the previous failure says the update "
      "rewrote too much of a file, do not return a complete changed_files replacement "
      "for that file. Return only exact search/replace edits around the requested "
      "handler, state, data, labels, or small JSX block. Preserve all unrelated layout, "
      "components, styles, copy, imports, and file structure. If the previous failure "
      "mentions an unapproved file or scope boundary, patch only the approved candidate "
      "file shown in this retry prompt and leave other files for later subtasks."
    )
  deterministic_changes = deterministic_undefined_reference_fix_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic fix for undefined reference crash.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "undefined_reference_fix",
    }
  deterministic_changes = deterministic_undefined_name_runtime_fix_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic guard for undefined .name runtime crash.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "undefined_name_runtime_fix",
    }
  deterministic_changes = deterministic_onboarding_chat_update_changes(
    prompt=effective_prompt,
    update_analysis=update_analysis,
    existing_files=candidate_files,
  )
  if deterministic_changes:
    return {
      "status": "completed",
      "summary": "Applied deterministic 5-step conversational onboarding chat component.",
      "edits": [],
      "changed_files": [
        {"path": file_item["path"], "code": file_item["content"]}
        for file_item in deterministic_changes
      ],
      "clarification_question": "",
      "deterministic_fallback": "onboarding_chat_flow",
    }
  scoped_edit_plan = build_scoped_edit_plan(
    effective_prompt,
    update_analysis=update_analysis,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  planned_update_analysis = {
    **update_analysis,
    "scoped_edit_plan": scoped_edit_plan,
  }
  scoped_prompt = build_scoped_update_patch_prompt(
    effective_prompt,
    update_analysis=planned_update_analysis,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  primary_scoped_prompt = scoped_prompt
  try:
    response = run_artifact_provider_with_soft_timeout(
      artifact_provider,
      primary_scoped_prompt,
      system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
      trace_label="scoped_update_artifact",
      response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
      max_output_tokens=SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
      timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
      prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy"],
      selected_files=candidate_paths,
    )
  except Exception as exc:
    if is_model_connection_error(exc):
      raise scoped_update_model_error(exc, phase="the primary patch call") from exc
    if not is_artifact_json_invalid_error(exc):
      raise
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        strict_scoped_update_retry_prompt(primary_scoped_prompt),
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "json_retry"],
        selected_files=candidate_paths,
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        raise scoped_update_model_error(retry_exc, phase="the strict JSON retry") from retry_exc
      if is_artifact_json_invalid_error(retry_exc):
        raise invalid_scoped_update_json_guard_error(retry_exc, phase="after strict JSON retry") from retry_exc
      raise
  normalized_response = normalize_scoped_update_response(response)
  if should_retry_empty_scoped_update_response(normalized_response):
    log_scoped_no_patch_response(
      normalized_response,
      update_analysis=planned_update_analysis,
      phase="primary",
    )
    retry_prompt = empty_scoped_update_retry_prompt(scoped_prompt)
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        retry_prompt,
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "empty_patch_retry"],
        selected_files=candidate_paths,
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        raise scoped_update_model_error(retry_exc, phase="the empty-patch retry") from retry_exc
      if is_artifact_json_invalid_error(retry_exc):
        raise invalid_scoped_update_json_guard_error(retry_exc, phase="while retrying an empty patch") from retry_exc
      raise
    normalized_response = normalize_scoped_update_response(response)
  if should_retry_empty_scoped_update_response(normalized_response):
    log_scoped_no_patch_response(
      normalized_response,
      update_analysis=planned_update_analysis,
      phase="retry",
    )
  normalized_response["_scoped_prompt"] = scoped_prompt
  normalized_response["_candidate_paths"] = candidate_paths
  return normalized_response
