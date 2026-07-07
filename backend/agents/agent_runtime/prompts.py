from __future__ import annotations

import json
from typing import Any

from .constants import (
  SCOPED_UPDATE_COMPACT_PROMPT_MAX_ANALYSIS_CHARS,
  SCOPED_UPDATE_COMPACT_PROMPT_MAX_EXCERPT_CHARS,
)
try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block


def build_supervisor_decision_prompt(
  *,
  goal: str,
  available_actions: list[dict[str, Any]],
  compact_tools: list[dict[str, Any]],
  state_summary: dict[str, Any],
  recent_observations: list[dict[str, Any]],
) -> str:
  return (
    "Return only JSON with keys next_agent, next_action, tools_to_call, reason, stop_or_continue.\n"
    f"Shared prompt policy: {prompt_policy_block(include_generation=True, include_update=True)}\n"
    f"Goal: {goal}\n"
    f"Available actions: {json.dumps(available_actions)}\n"
    f"Available backend tools: {json.dumps(compact_tools)}\n"
    f"Current runtime state: {json.dumps(state_summary)}\n"
    f"Recent observations: {json.dumps(recent_observations)}"
  )


def build_review_agent_prompt(*, prompt: str, brief: dict[str, Any], plan: dict[str, Any]) -> str:
  return (
    "Return JSON with keys: status, issues, recommendations.\n"
    f"Shared prompt policy: {prompt_policy_block(include_generation=True, include_update=True)}\n"
    f"{prompt}\n"
    f"Brief: {json.dumps(brief)}\n"
    f"Plan: {json.dumps(plan)}"
  )


def build_prompt_analyst_runtime_prompt(
  *,
  operation: str,
  user_prompt: str,
  routing_result: dict[str, Any],
  file_index: list[dict[str, Any]],
  existing_files: list[dict[str, Any]],
  memories: list[dict[str, Any]],
) -> str:
  task_label = "project update prompt analyst" if operation == "update" else "project prompt analyst"
  key_list = (
    "business_type, audience, goal, style, required_sections, backend_stack, database_stack, entities, endpoints, missing_information, update_goal, files_to_preserve, likely_files_to_change"
    if operation == "update"
    else "business_type, audience, goal, style, required_sections, backend_stack, database_stack, entities, endpoints, missing_information"
  )
  return (
    f"Return only JSON for a {task_label} agent with keys: "
    f"{key_list}. "
    f"Shared prompt policy: {prompt_policy_block(include_generation=operation != 'update', include_update=operation == 'update')}\n"
    f"User prompt: {user_prompt}\n"
    f"Routing result: {_json_for_prompt(routing_result, max_chars=4_000)}\n"
    f"Project file keyword index: {_json_for_prompt(file_index, max_chars=10_000)}\n"
    f"Existing files: {_json_for_prompt(existing_files, max_chars=24_000)}\n"
    f"Relevant memory: {_json_for_prompt(memories, max_chars=14_000)}"
  )


def build_planner_runtime_prompt(
  *,
  operation: str,
  user_prompt: str,
  brief: dict[str, Any],
  memories: list[dict[str, Any]],
  prepared_section_keys: list[str],
) -> str:
  key_list = (
    "sections, layout_strategy, interactions, backend_architecture, database_design, api_contracts, integration_strategy, quality_checks, update_strategy, files_to_change, preserve_rules"
    if operation == "update"
    else "sections, layout_strategy, interactions, backend_architecture, database_design, api_contracts, integration_strategy, quality_checks"
  )
  return (
    "Return only JSON for a project planner agent with keys: "
    f"{key_list}. "
    f"Shared prompt policy: {prompt_policy_block(include_generation=True, include_update=operation == 'update')}\n"
    f"User prompt: {user_prompt}\n"
    f"Brief: {_json_for_prompt(brief, max_chars=24_000)}\n"
    f"Relevant memory: {_json_for_prompt(memories, max_chars=14_000)}\n"
    f"Pipeline context keys: {prepared_section_keys}"
  )


def render_compact_scoped_update_retry_prompt(
  *,
  user_prompt: str,
  update_analysis: dict[str, Any],
  allowed_paths: list[str],
  excerpts: list[dict[str, Any]],
  retry_reason: str | None = None,
) -> str:
  retry_instruction = (
    f"\nPrevious scoped update problem:\n{retry_reason.strip()}\n\nRetry now with the smallest valid patch.\n"
    if isinstance(retry_reason, str) and retry_reason.strip()
    else "\nMake the smallest valid scoped patch for the approved files.\n"
  )
  return f"""
User update request:
{user_prompt.strip()}

Approved scoped update analysis:
{_json_for_prompt(update_analysis, max_chars=SCOPED_UPDATE_COMPACT_PROMPT_MAX_ANALYSIS_CHARS)}

Allowed existing file paths:
{_json_for_prompt(allowed_paths, max_chars=2000)}

Focused raw source excerpts from the allowed files:
{_json_for_prompt(excerpts, max_chars=SCOPED_UPDATE_COMPACT_PROMPT_MAX_EXCERPT_CHARS)}
{retry_instruction}

Rules:
- Shared prompt policy:
{prompt_policy_block(include_generation=False, include_update=True)}
- Return one compact JSON object only.
- Return status "completed" only when edits or changed_files is non-empty.
- If update_analysis.scoped_edit_plan is present, follow its allowed paths,
  approved new paths, operations, and anchors exactly.
- You are an expert web development agent. When modifying an existing codebase,
  do not guess line numbers or use broken tool calls. Instead, output explicit
  SEARCH/REPLACE blocks.
- For theme/color/style/visual updates, inspect the allowed source excerpts and
  update the actual project-owned CSS variables, classes, inline styles,
  gradients, and rendered component markup in this file. Do not rely on backend
  static palettes or generic regex assumptions. If another rendered source file
  owns the remaining visible old styling, return needs_scope_expansion with the
  exact path.
- Prefer edits. For every edit.search_replace, copy the SEARCH side exactly
  from the focused excerpts above. Do not include line numbers or commentary.
- Never ask the user to provide file contents, snippets, imports, state
  declarations, or the top/bottom of a source file. The backend owns source
  retrieval; use the focused excerpts and scoped_edit_plan anchors.
- If a new component/helper path is listed in update_analysis.candidate_new_files,
  you may include that exact new path in changed_files, but you must also edit an
  existing allowed file to import or render it.
- Never return empty edits and empty changed_files when scoped_edit_plan has an
  anchor for an allowed path. If you genuinely cannot identify the user target,
  return status "needs_clarification" with one concrete clarification_question.
- If this subtask requires another existing project file that is not listed in
  allowed_paths, return status "needs_scope_expansion" with that exact path in
  requested_files. Do not ask the user for permission to edit a project file.
- Do not return markdown, generated_website, implementation_notes, nested
  wrappers, prose, or any unapproved path.

Required JSON shape:
{{
  "status": "completed",
  "summary": "short patch summary",
  "edits": [
    {{
      "path": "one approved existing path",
      "search_replace": "<<<<<<< SEARCH\nexact source excerpt copied from above\n=======\nreplacement source\n>>>>>>> REPLACE",
      "search": "exact source excerpt copied from above",
      "replace": "replacement source",
      "expected_replacements": 1
    }}
  ],
  "changed_files": [],
  "requested_files": [],
  "clarification_question": ""
}}
"""


def strict_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return (
    f"{scoped_prompt}\n\n"
    "Your previous scoped update response was rejected because it was not valid JSON. "
    "Retry now with ONE compact JSON object only. Do not include markdown, explanations, "
    "implementation_notes, generated_website, files wrappers, or extra keys. Prefer edits "
    "with edits[].search_replace SEARCH/REPLACE blocks copied from current file content. "
    "If exact edits are unsafe, return changed_files with complete code for only the allowed "
    "file paths. Escape every double quote inside code strings and encode every line break "
    "inside search_replace, search, replace, and code values as \\n."
  )


def empty_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return (
    f"{scoped_prompt}\n\n"
    "Your previous scoped update response returned no usable edits or changed_files. "
    "Retry once with a minimal patch. Return status completed only if you include at "
    "least one edits item or changed_files item. Prefer edits with edits[].search_replace "
    "SEARCH/REPLACE blocks copied from the current file content. If search/replace is "
    "unsafe, return changed_files with the complete updated file code for only the "
    "allowed path(s). Do not return an empty patch, identical unchanged code, wrapper "
    "objects, markdown, or explanations."
  )


def no_effective_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return (
    f"{scoped_prompt}\n\n"
    "Your previous scoped update response was marked completed but produced no effective "
    "file changes. The edits either matched nothing, repeated the existing code, or "
    "changed_files was identical to the current source. Retry once with a real patch. "
    "Prefer changed_files with the complete updated file content for the allowed path(s). "
    "If you use edits, copy exact SEARCH blocks from the current file content and ensure "
    "the replacement actually changes the requested data, labels, handlers, or JSX. "
    "Return status completed only when at least one allowed file will differ from the "
    "current source after the patch is applied."
  )


def _json_for_prompt(value: Any, *, max_chars: int) -> str:
  try:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  except TypeError:
    text = json.dumps(str(value), ensure_ascii=False)
  if len(text) <= max_chars:
    return text
  return json.dumps(
    {
      "_truncated": True,
      "original_chars": len(text),
      "preview": text[:max_chars],
    },
    ensure_ascii=False,
    separators=(",", ":"),
  )
