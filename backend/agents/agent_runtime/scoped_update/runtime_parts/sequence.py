from __future__ import annotations

from typing import Any

try:
  from backend.debug_trace import trace_function
except ImportError:
  from debug_trace import trace_function

from backend.agents.prompt_context import current_user_prompt
from backend.agents.agent_runtime.file_ops import merge_project_file_changes
from backend.agents.agent_runtime.values import list_value, string_list, text_or_default
from backend.agents.agent_runtime.errors import ScopedUpdateGuardError
from backend.agents.agent_runtime.model_agents import run_artifact_provider_with_soft_timeout
from backend.agents.agent_runtime.fallbacks import is_artifact_json_invalid_error, is_model_connection_error
from backend.agents.agent_runtime.schemas import SCOPED_UPDATE_RESPONSE_SCHEMA
from backend.agents.agent_runtime.scoped_update.runtime_parts.agent import run_scoped_update_agent
from backend.agents.agent_runtime.scoped_update.runtime_parts.expansion import resolve_scoped_update_scope_expansion, scoped_update_scope_expansion_retry_prompt
from backend.agents.agent_runtime.scoped_update.generation import collect_deterministic_scoped_update_fallback_changes
from backend.agents.agent_runtime.scoped_update.runtime_parts.policy import (
  SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_TASKS,
  SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS,
  SCOPED_UPDATE_SYSTEM_INSTRUCTION,
  ScopeExpansionCallback,
  scoped_update_call_timeout_seconds,
)
from backend.agents.agent_runtime.scoped_update.prompting import (
  code_search_matches_for_task,
  empty_scoped_update_retry_prompt,
  log_scoped_no_patch_response,
  no_effective_scoped_update_retry_prompt,
  strict_scoped_update_retry_prompt,
)
from backend.agents.agent_runtime.scoped_update.response_parts import normalize_scoped_update_response, should_retry_empty_scoped_update_response
from backend.agents.agent_runtime.scoped_update.task_parts import (
  invalid_scoped_update_json_guard_error,
  is_no_effective_scoped_guard_error,
  is_no_patch_scoped_guard_error,
  scoped_update_analysis_for_task,
  scoped_update_prompt_for_task,
)
from backend.agents.agent_runtime.scoped_update.workflow_parts import validate_scoped_update_changes


def _raise_zero_aggregate_scoped_update_error(
  *,
  task_results: list[dict[str, Any]],
  update_analysis: dict[str, Any],
) -> None:
  candidate_paths: list[str] = []
  for task in list_value(update_analysis.get("scoped_update_tasks")):
    if not isinstance(task, dict):
      continue
    for path in string_list(task.get("candidate_files"), []):
      if path not in candidate_paths:
        candidate_paths.append(path)
  if not candidate_paths:
    candidate_paths = string_list(update_analysis.get("candidate_files"), [])
  task_ids = [
    text_or_default(task.get("id"), "")
    for task in task_results
    if isinstance(task, dict) and text_or_default(task.get("id"), "")
  ]
  detail = ""
  if task_ids:
    detail += f" Subtasks: {', '.join(task_ids[:6])}."
  if candidate_paths:
    detail += f" Candidate files: {', '.join(candidate_paths[:8])}."
  interaction = update_analysis.get("interaction") if isinstance(update_analysis.get("interaction"), dict) else {}
  if interaction:
    component = text_or_default(interaction.get("component"), "")
    trigger = text_or_default(interaction.get("trigger"), "")
    expected = text_or_default(interaction.get("expected"), "")
    target = text_or_default(interaction.get("target_page_or_route"), "")
    contract = ", ".join(part for part in (component, trigger, expected, target) if part)
    if contract:
      detail += f" Interaction contract: {contract[:500]}."
  profile = text_or_default(update_analysis.get("enrichment_profile"), "")
  if profile:
    detail += f" Scope profile: {profile}."
  raise ScopedUpdateGuardError(
    "Scoped update produced zero changed files after running the scoped subtasks. "
    "The update agent produced no file edits, so the existing website was preserved."
    + detail
  )

def run_scoped_update_task_with_expansion(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None,
  deadline_monotonic: float | None,
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
  task_id: str = "scoped_update",
  task_index: int = 1,
  scope_expansion_callback: ScopeExpansionCallback | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any], list[dict[str, Any]]]:
  current_analysis = dict(update_analysis)
  current_prompt = prompt
  scope_expansions: list[dict[str, Any]] = []
  while True:
    current_matches = code_search_matches_for_task(code_search_matches, current_analysis)
    scoped_result = run_scoped_update_agent(
      artifact_provider,
      prompt=current_prompt,
      update_analysis=current_analysis,
      existing_files=existing_files,
      code_search_matches=current_matches,
      previous_error=previous_error,
      deadline_monotonic=deadline_monotonic,
    )
    if text_or_default(scoped_result.get("status"), "") == "needs_scope_expansion":
      if len(scope_expansions) >= SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS:
        raise ScopedUpdateGuardError(
          "Scoped update exceeded the two-attempt internal scope-expansion limit. "
          "The existing website was preserved."
        )
      current_analysis, event = resolve_scoped_update_scope_expansion(
        scoped_result,
        update_analysis=current_analysis,
        existing_files=existing_files,
        retry_count=len(scope_expansions) + 1,
      )
      event.update({"task_id": task_id, "task_index": task_index})
      scope_expansions.append(event)
      if scope_expansion_callback is not None:
        scope_expansion_callback(dict(event))
      current_prompt = scoped_update_scope_expansion_retry_prompt(prompt, event)
      continue

    try:
      changed_files = validate_scoped_update_changes(
        scoped_result,
        update_analysis=current_analysis,
        existing_files=existing_files,
      )
    except ScopedUpdateGuardError as exc:
      recovered = recover_scoped_update_guard_failure(
        exc,
        artifact_provider=artifact_provider,
        scoped_result=scoped_result,
        prompt=current_prompt,
        update_analysis=current_analysis,
        existing_files=existing_files,
        deadline_monotonic=deadline_monotonic,
        task=task,
        working_files=working_files,
        created_candidate_paths=created_candidate_paths,
      )
      if recovered is None:
        raise
      scoped_result, changed_files = recovered
    scoped_result["scope_expansions"] = scope_expansions
    return scoped_result, changed_files, current_analysis, scope_expansions


def recover_scoped_update_guard_failure(
  exc: ScopedUpdateGuardError,
  *,
  artifact_provider: Any,
  scoped_result: dict[str, Any],
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  deadline_monotonic: float | None,
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]] | None:
  if not is_no_patch_scoped_guard_error(exc):
    return None

  scoped_prompt = text_or_default(scoped_result.get("_scoped_prompt"), "")
  if is_no_effective_scoped_guard_error(exc) and scoped_prompt:
    try:
      response = run_artifact_provider_with_soft_timeout(
        artifact_provider,
        no_effective_scoped_update_retry_prompt(scoped_prompt),
        system_instruction=SCOPED_UPDATE_SYSTEM_INSTRUCTION,
        trace_label="scoped_update_artifact",
        response_schema=SCOPED_UPDATE_RESPONSE_SCHEMA,
        max_output_tokens=SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
        timeout_seconds=scoped_update_call_timeout_seconds(deadline_monotonic),
        prompt_fragments_used=["user_prompt", "scoped_update_analysis", "selected_file_excerpts", "patch_policy", "no_effective_change_retry"],
        selected_files=string_list(scoped_result.get("_candidate_paths"), []),
      )
    except Exception as retry_exc:
      if is_model_connection_error(retry_exc):
        pass
      elif is_artifact_json_invalid_error(retry_exc):
        pass
      else:
        raise
    else:
      retry_result = normalize_scoped_update_response(response)
      retry_result["_scoped_prompt"] = scoped_prompt
      try:
        changed_files = validate_scoped_update_changes(
          retry_result,
          update_analysis=update_analysis,
          existing_files=existing_files,
        )
      except ScopedUpdateGuardError:
        pass
      else:
        return retry_result, changed_files

  fallback_changes, fallback_kind = collect_deterministic_scoped_update_fallback_changes(
    prompt=prompt,
    update_analysis=update_analysis,
    existing_files=existing_files,
    task=task,
    working_files=working_files,
    created_candidate_paths=created_candidate_paths,
  )
  if not fallback_changes:
    return None

  recovered_result = {
    "status": "completed",
    "summary": "Applied bounded deterministic scoped fallback after Gemini returned no usable scoped patch.",
    "edits": [],
    "changed_files": [
      {"path": file_item["path"], "code": file_item["content"]}
      for file_item in fallback_changes
    ],
    "clarification_question": "",
    "deterministic_fallback": fallback_kind or "scoped_update_recovery",
  }
  return recovered_result, fallback_changes


@trace_function(task_count=lambda _artifact_provider, **kwargs: len((kwargs.get("update_analysis") or {}).get("scoped_update_tasks") or []), previous_error=lambda _artifact_provider, **kwargs: "yes" if kwargs.get("previous_error") else "no")
def run_scoped_update_sequence(
  artifact_provider: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  code_search_matches: list[dict[str, Any]],
  previous_error: str | None = None,
  deadline_monotonic: float | None = None,
  scope_expansion_callback: ScopeExpansionCallback | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, Any]]]:
  prompt = current_user_prompt(prompt)
  tasks = [
    task
    for task in list_value(update_analysis.get("scoped_update_tasks"))
    if isinstance(task, dict)
  ][:SCOPED_UPDATE_MAX_TASKS]
  if len(tasks) <= 1:
    scoped_result, changed_files, _final_analysis, _scope_expansions = run_scoped_update_task_with_expansion(
      artifact_provider,
      prompt=prompt,
      update_analysis=update_analysis,
      existing_files=existing_files,
      code_search_matches=code_search_matches,
      previous_error=previous_error,
      deadline_monotonic=deadline_monotonic,
      task=tasks[0] if tasks else None,
      task_id=text_or_default(tasks[0].get("id"), "scoped_update") if tasks else "scoped_update",
      scope_expansion_callback=scope_expansion_callback,
    )
    return scoped_result, changed_files, []

  working_files = [dict(file_item) for file_item in existing_files]
  original_existing_paths = {
    text_or_default(file_item.get("path"), "")
    for file_item in existing_files
    if isinstance(file_item, dict)
  }
  created_candidate_paths: list[str] = []
  final_changed_by_path: dict[str, str] = {}
  changed_path_order: list[str] = []
  task_results: list[dict[str, Any]] = []
  prior_task_memory: list[str] = []
  all_scope_expansions: list[dict[str, Any]] = []
  for index, task in enumerate(tasks):
    stop_after_current_task = False
    task_analysis = scoped_update_analysis_for_task(
      update_analysis,
      task,
      working_files,
      additional_candidate_files=created_candidate_paths,
    )
    task_prompt = scoped_update_prompt_for_task(
      root_prompt=prompt,
      task=task,
      index=index,
      total=len(tasks),
      prior_task_memory=prior_task_memory,
      previous_error=previous_error if index == 0 else None,
    )
    task_result, task_changed_files, task_analysis, task_scope_expansions = run_scoped_update_task_with_expansion(
      artifact_provider,
      prompt=task_prompt,
      update_analysis=task_analysis,
      existing_files=working_files,
      code_search_matches=code_search_matches,
      previous_error=previous_error if index == 0 else None,
      deadline_monotonic=deadline_monotonic,
      task=task,
      working_files=working_files,
      created_candidate_paths=created_candidate_paths,
      task_id=text_or_default(task.get("id"), f"step_{index + 1}"),
      task_index=index + 1,
      scope_expansion_callback=scope_expansion_callback,
    )
    all_scope_expansions.extend(task_scope_expansions)
    stop_after_current_task = text_or_default(task_result.get("deterministic_fallback"), "") == "created_component_content"
    working_files = merge_project_file_changes(working_files, task_changed_files)
    task_changed_paths = [file_item["path"] for file_item in task_changed_files]
    for path in task_changed_paths:
      if path not in original_existing_paths and path not in created_candidate_paths:
        created_candidate_paths.append(path)
    for file_item in task_changed_files:
      path = file_item["path"]
      final_changed_by_path[path] = file_item["content"]
      if path not in changed_path_order:
        changed_path_order.append(path)
    task_summary = {
      "id": text_or_default(task.get("id"), f"step_{index + 1}"),
      "index": index + 1,
      "summary": text_or_default(task.get("summary"), text_or_default(task_result.get("summary"), "")),
      "prompt": text_or_default(task.get("prompt"), "")[:500],
      "candidate_files": string_list(task_analysis.get("candidate_files"), []),
      "candidate_new_files": string_list(task_analysis.get("candidate_new_files"), []),
      "changed_file_paths": task_changed_paths,
      "status": text_or_default(task_result.get("status"), "completed"),
      "scope_expansions": task_scope_expansions,
    }
    task_results.append(task_summary)
    prior_task_memory.append(
      f"Step {index + 1} changed {', '.join(task_changed_paths)}: "
      f"{task_summary['summary']}"
    )
    if stop_after_current_task:
      break

  changed_files = [
    {"path": path, "content": final_changed_by_path[path]}
    for path in changed_path_order
    if path in final_changed_by_path
  ]
  if not changed_files:
    _raise_zero_aggregate_scoped_update_error(
      task_results=task_results,
      update_analysis=update_analysis,
    )
  return (
    {
      "status": "completed",
      "summary": f"Applied {len(task_results)} scoped update subtasks.",
      "edits": [],
      "changed_files": [{"path": item["path"], "code": item["content"]} for item in changed_files],
      "requested_files": [],
      "clarification_question": "",
      "task_results": task_results,
      "scope_expansions": all_scope_expansions,
    },
    changed_files,
    task_results,
  )
