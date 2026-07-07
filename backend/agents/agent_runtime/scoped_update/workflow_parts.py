from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from ...artifacts import normalize_artifact_path, normalize_generated_file_code
from ..constants import SCOPED_UPDATE_MAX_NEW_FILES, SCOPED_UPDATE_MAX_TASKS
from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..file_ops import tool_files_to_artifact_files
from ..update_analysis import normalize_scoped_update_candidate_new_files
from ..values import list_value, object_value, string_list, text_or_default
from .response_parts import (
  is_actionable_scoped_clarification,
  normalize_scoped_update_response,
  scoped_update_has_effective_change,
  apply_scoped_update_edit,
  should_retry_empty_scoped_update_response,
)


def scoped_update_request_text(prompt: str, update_analysis: dict[str, Any]) -> str:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  diagnosis = object_value(update_analysis.get("error_diagnosis"))
  parts = [
    prompt,
    text_or_default(update_analysis.get("summary"), ""),
    " ".join(string_list(update_analysis.get("target_symbols"), [])),
    text_or_default(feature_plan.get("name"), ""),
    " ".join(string_list(feature_plan.get("items"), [])),
    text_or_default(feature_plan.get("interaction"), ""),
    " ".join(string_list(diagnosis.get("root_cause_hints"), [])),
    " ".join(string_list(diagnosis.get("categories"), [])),
    " ".join(string_list(diagnosis.get("mentioned_paths"), [])),
  ]
  return " ".join(part for part in parts if part)

def validate_scoped_update_changes(
  response: Any,
  *,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  raw = normalize_scoped_update_response(response)
  status = text_or_default(raw.get("status"), "blocked")
  if status == "needs_scope_expansion":
    requested_files = string_list(raw.get("requested_files"), [])
    requested_text = ", ".join(requested_files) if requested_files else "an unspecified project file"
    raise ScopedUpdateGuardError(
      "Scoped update requested unresolved internal scope expansion for "
      f"{requested_text}. The existing website was preserved."
    )
  if status == "needs_clarification":
    clarification = text_or_default(raw.get("clarification_question"), "")
    if not is_actionable_scoped_clarification(clarification):
      raise ScopedUpdateGuardError(
        "Scoped update was blocked before project modification: "
        "Gemini returned no scoped edits or changed files for the approved files."
      )
    raise UpdateRequestNeedsClarificationError(
      "Update request needs clarification before editing files: "
      + text_or_default(clarification, "Please identify the exact update target.")
    )
  if status != "completed":
    reason = (
      text_or_default(raw.get("summary"), "")
      or text_or_default(raw.get("clarification_question"), "")
      or "Gemini returned no scoped edits or changed files for the approved files."
    )
    raise ScopedUpdateGuardError(
      f"Scoped update was blocked before project modification: {reason}"
    )
  allowed_paths = set(string_list(update_analysis.get("candidate_files"), []))
  existing_by_path = {file_item["path"]: file_item["content"] for file_item in existing_files}
  update_mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  approved_new_paths = set(
    normalize_scoped_update_candidate_new_files(
      update_analysis.get("candidate_new_files"),
      existing_paths=list(existing_by_path),
      update_mode=update_mode,
    )
  )
  maximum_change_fraction = 0.45 if update_mode in {"targeted_patch", "bug_fix"} else 0.80
  changed_files: list[dict[str, str]] = []
  changed_existing_paths: set[str] = set()
  changed_new_paths: set[str] = set()
  seen: set[str] = set()
  edited_by_path: dict[str, str] = {}
  for item in list_value(raw.get("edits")):
    if not isinstance(item, dict):
      continue
    try:
      path = normalize_artifact_path(text_or_default(item.get("path"), ""))
    except Exception as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid edit path: {exc}") from exc
    if path not in allowed_paths or path not in existing_by_path:
      raise ScopedUpdateGuardError(f"Scoped update attempted to edit unapproved file {path}.")
    search = item.get("search")
    replacement = item.get("replace")
    if not isinstance(search, str) or not search:
      raise ScopedUpdateGuardError(f"Scoped update returned an empty search snippet for {path}.")
    if not isinstance(replacement, str):
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid replacement snippet for {path}.")
    try:
      expected_replacements = int(item.get("expected_replacements", 1))
    except (TypeError, ValueError) as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid replacement count for {path}.") from exc
    if expected_replacements < 1 or expected_replacements > 20:
      raise ScopedUpdateGuardError(f"Scoped update replacement count for {path} is outside the safe limit.")
    current = edited_by_path.get(path, existing_by_path[path])
    edited_by_path[path] = apply_scoped_update_edit(
      current=current,
      search=search,
      replacement=replacement,
      expected_replacements=expected_replacements,
      path=path,
    )
  if len(list_value(raw.get("edits"))) > 20:
    raise ScopedUpdateGuardError("Scoped update exceeded the twenty-edit safety limit.")
  for path, code in edited_by_path.items():
    seen.add(path)
    normalized_code = normalize_generated_file_code(path, code)
    previous = existing_by_path[path]
    if not scoped_update_has_effective_change(path, previous, code):
      continue
    normalized_previous = normalize_generated_file_code(path, previous)
    change_fraction = 1.0 - SequenceMatcher(None, normalized_previous, normalized_code).ratio()
    allowed_change_fraction = scoped_update_allowed_change_fraction(
      update_analysis,
      path=path,
      previous=previous,
      candidate=normalized_code,
      default=maximum_change_fraction,
    )
    if change_fraction > allowed_change_fraction:
      raise ScopedUpdateGuardError(
        f"Scoped update edits attempted to rewrite too much of {path} "
        f"({change_fraction:.0%} changed; allowed {allowed_change_fraction:.0%}). "
        "The existing website was preserved."
      )
    changed_existing_paths.add(path)
    changed_files.append({"path": path, "content": normalized_code})
  for item in list_value(raw.get("changed_files")):
    if not isinstance(item, dict):
      continue
    try:
      path = normalize_artifact_path(text_or_default(item.get("path"), ""))
    except Exception as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid path: {exc}") from exc
    if path in seen:
      raise ScopedUpdateGuardError(f"Scoped update returned duplicate changes for {path}.")
    seen.add(path)
    is_existing_path = path in existing_by_path
    is_approved_new_path = path in approved_new_paths
    if is_existing_path and path not in allowed_paths:
      raise ScopedUpdateGuardError(f"Scoped update attempted to modify unapproved file {path}.")
    if not is_existing_path and not is_approved_new_path:
      raise ScopedUpdateGuardError(f"Scoped update attempted to modify unapproved file {path}.")
    code = item.get("code")
    if not isinstance(code, str) or not code.strip():
      raise ScopedUpdateGuardError(f"Scoped update returned empty or invalid code for {path}.")
    normalized_code = normalize_generated_file_code(path, code)
    if is_existing_path:
      previous = existing_by_path[path]
      if not scoped_update_has_effective_change(path, previous, code):
        continue
      normalized_previous = normalize_generated_file_code(path, previous)
      change_fraction = 1.0 - SequenceMatcher(None, normalized_previous, normalized_code).ratio()
      allowed_change_fraction = scoped_update_allowed_change_fraction(
        update_analysis,
        path=path,
        previous=previous,
        candidate=normalized_code,
        default=maximum_change_fraction,
      )
      if change_fraction > allowed_change_fraction:
        raise ScopedUpdateGuardError(
          f"Scoped update attempted to rewrite too much of {path} "
          f"({change_fraction:.0%} changed; allowed {allowed_change_fraction:.0%}). "
          "The existing website was preserved."
        )
      changed_existing_paths.add(path)
    else:
      changed_new_paths.add(path)
    changed_files.append({"path": path, "content": normalized_code})
  if not changed_files:
    raise ScopedUpdateGuardError("Scoped update returned no effective file changes. The existing website was preserved.")
  if changed_new_paths and not changed_existing_paths:
    raise ScopedUpdateGuardError(
      "Scoped update created a new file without modifying an approved existing integration file. "
      "The existing website was preserved."
    )
  if len(changed_existing_paths) > 4:
    raise ScopedUpdateGuardError("Scoped update exceeded the four-existing-file change limit. The existing website was preserved.")
  if len(changed_new_paths) > SCOPED_UPDATE_MAX_NEW_FILES:
    raise ScopedUpdateGuardError("Scoped update exceeded the two-new-file change limit. The existing website was preserved.")
  return changed_files


def scoped_update_allowed_change_fraction(
  update_analysis: dict[str, Any],
  *,
  path: str,
  previous: str,
  candidate: str,
  default: float,
) -> float:
  if is_onboarding_chat_component_rewrite(update_analysis, path=path, previous=previous, candidate=candidate):
    return 1.0
  if text_or_default(update_analysis.get("request_kind"), "") == "interaction_wiring_update":
    return max(default, 0.65)
  if text_or_default(update_analysis.get("enrichment_profile"), "") == "interaction_wiring":
    return max(default, 0.65)
  return default


def is_onboarding_chat_component_rewrite(
  update_analysis: dict[str, Any],
  *,
  path: str,
  previous: str,
  candidate: str,
) -> bool:
  if text_or_default(update_analysis.get("update_mode"), "") != "feature_patch":
    return False
  request_text = scoped_update_request_text("", update_analysis).lower()
  path_key = path.lower()
  if "onboarding" not in request_text or not any(marker in request_text for marker in ("chat", "conversational", "conversation", "ai chat")):
    return False
  if not any(marker in request_text for marker in ("5", "five", "step")):
    return False
  if "onboarding" not in path_key and "wizard" not in path_key:
    return False
  candidate_key = candidate.lower()
  required_markers = ("onboardingsteps", "activestep", "oncomplete")
  return all(marker in candidate_key for marker in required_markers)


def scoped_update_generated_website(
  *,
  title: str,
  prompt: str,
  update_analysis: dict[str, Any],
  candidate_files: list[dict[str, str]],
  changed_paths: list[str],
) -> dict[str, Any]:
  mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  return {
    "title": title,
    "headline": f"{title} scoped update applied",
    "subheadline": f"Applied the requested {mode.replace('_', ' ')} while preserving unrelated project code.",
    "primary_cta": "Review preview",
    "secondary_cta": "Review changed files",
    "preview_html": "",
    "sections": [
      {
        "name": "Scoped update",
        "purpose": "Apply only the requested existing-project change.",
        "content": text_or_default(update_analysis.get("summary"), prompt),
        "items": changed_paths,
      }
    ],
    "files": tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_paths),
  }


def scoped_update_workflow_plan(update_analysis: dict[str, Any], changed_paths: list[str]) -> dict[str, Any]:
  mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  scoped_tasks = [
    task for task in list_value(update_analysis.get("scoped_update_tasks")) if isinstance(task, dict)
  ][:SCOPED_UPDATE_MAX_TASKS]
  if len(scoped_tasks) > 1:
    tasks = []
    for index, task in enumerate(scoped_tasks):
      task_id = text_or_default(task.get("id"), f"scoped_update_{index + 1}")
      previous_task_id = text_or_default(scoped_tasks[index - 1].get("id"), f"scoped_update_{index}") if index else ""
      tasks.append(
        {
          "id": task_id,
          "name": text_or_default(task.get("summary"), f"Scoped update step {index + 1}"),
          "required_capability": mode,
          "runtime_action": "RUN_SCOPED_UPDATE_AGENT",
          "dependencies": [previous_task_id] if previous_task_id else [],
          "risk_level": "medium",
          "optional": False,
        }
      )
    task_ids = [task["id"] for task in tasks]
    dependency_graph = {
      task_id: ([task_ids[index - 1]] if index else [])
      for index, task_id in enumerate(task_ids)
    }
  else:
    tasks = [
      {
        "id": "scoped_update",
        "name": "Scoped existing-project update",
        "required_capability": mode,
        "runtime_action": "RUN_SCOPED_UPDATE_AGENT",
        "dependencies": [],
        "risk_level": "medium",
        "optional": False,
      }
    ]
    task_ids = ["scoped_update"]
    dependency_graph = {"scoped_update": []}
  return {
    "domain": "existing_project_update",
    "scope": text_or_default(update_analysis.get("scope"), "small"),
    "tasks": tasks,
    "assignments": [],
    "dependency_graph": dependency_graph,
    "parallel_groups": [[task_id] for task_id in task_ids],
    "completion_proof": ["artifact_valid", "staged_preview_ready", "visual_qa_passed", "files_committed", "memory_prepared"],
    "active_agents": [
      {
        "id": f"{mode}-agent",
        "name": "Scoped Update Agent",
        "role": "Patch only approved existing source files.",
        "capabilities": [mode],
        "lifecycle": "core",
        "assigned_tasks": task_ids,
      }
    ],
    "created_agent_ids": [],
    "reused_agent_ids": [f"{mode}-agent"],
    "planning_source": "gemini_update_analysis_with_python_guardrails",
    "planner_reason": f"Changed only {', '.join(changed_paths)} and skipped the full dynamic workflow.",
  }
