from __future__ import annotations

from typing import Any

from ....project_workspace import needs_vite_scaffold_repair
from ...constants import RUNTIME_IMPORT_SHIM_PATHS
from ...progress import (
  emit_runtime_progress,
  is_missing_vite_entry_reason,
  is_unsafe_bare_react_reason,
  normalize_candidate_react_imports,
  preview_build_failure_reason,
  sync_generated_website_files_from_candidates,
)
from ...scaffolding import ensure_tailwind_runtime_files, ensure_vite_scaffold_files, normalize_frontend_runtime_imports
from ...state import append_step
from ...tooling import record_deterministic_repair_event
from ...values import list_value, object_value, text_or_default

INTERACTION_PROBLEM_TERMS = (
  "not working",
  "doesn't work",
  "does not work",
  "is not working",
  "not clickable",
  "can't click",
  "cannot click",
  "nothing happens",
  "broken",
)

INTERACTION_TARGET_TERMS = (
  "button",
  "click",
  "clicked",
  "clicking",
  "fix the action",
  "fix action",
  "handler",
  "submit",
  "dropdown",
  "modal",
  "toggle",
)

INTERACTION_CODE_MARKERS = (
  "onClick",
  "onSubmit",
  "onChange",
  "addEventListener",
  "preventDefault",
  "setCurrent",
  "setActive",
  "setShow",
  "setOpen",
  "navigate(",
  "window.location",
  "href=",
  'role="button"',
)

VISUAL_QA_REQUIRED_TERMS = (
  "layout",
  "responsive",
  "mobile",
  "desktop",
  "alignment",
  "align",
  "overlap",
  "overflow",
  "scroll",
  "color",
  "theme",
  "dark",
  "light",
  "style",
  "design",
  "spacing",
  "padding",
  "margin",
  "font",
  "text visible",
  "not visible",
)


def is_unresolved_preview_runtime_import_reason(reason: str) -> bool:
  lowered = str(reason or "").lower()
  if "failed to resolve import" not in lowered and "rollup failed to resolve import" not in lowered:
    return False
  return any(module_name.lower() in lowered for module_name in RUNTIME_IMPORT_SHIM_PATHS)


def normalize_preview_candidate_files(
  state: dict[str, Any],
  *,
  agent: str = "Validation Agent",
  record_steps: bool = True,
) -> list[str]:
  touched_paths: list[str] = []
  title = text_or_default(object_value(state.get("generated_website")).get("title"), "Generated Website")
  files = list(state.get("candidate_files") or [])

  scaffolded_files, scaffold_paths = (files, [])
  if needs_vite_scaffold_repair(files):
    scaffolded_files, scaffold_paths = ensure_vite_scaffold_files(files, title=title)
  if scaffold_paths:
    state["candidate_files"] = scaffolded_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(scaffold_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_vite_scaffold_normalization",
        reason="Added missing Vite scaffold files before staged preview build.",
        paths=scaffold_paths,
      )
      append_step(
        state,
        agent,
        "normalize_vite_scaffold_before_preview",
        {"missing_paths": scaffold_paths},
        {"status": "normalized", "paths": scaffold_paths},
      )
    files = scaffolded_files

  tailwind_files, tailwind_paths = ensure_tailwind_runtime_files(files)
  if tailwind_paths:
    state["candidate_files"] = tailwind_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(tailwind_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_tailwind_runtime_normalization",
        reason="Generated source used Tailwind utilities without a complete Tailwind runtime scaffold.",
        paths=tailwind_paths,
      )
      append_step(
        state,
        agent,
        "normalize_tailwind_runtime_before_preview",
        {"paths": tailwind_paths},
        {"status": "normalized", "paths": tailwind_paths},
      )
    files = tailwind_files

  normalized_files, normalized_paths = normalize_candidate_react_imports(files)
  if normalized_paths:
    state["candidate_files"] = normalized_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(normalized_paths)
    if record_steps:
      append_step(
        state,
        agent,
        "normalize_react_imports_before_preview",
        {"paths": normalized_paths},
        {"status": "normalized", "paths": normalized_paths},
      )
    files = normalized_files

  runtime_import_files, runtime_import_paths = normalize_frontend_runtime_imports(files)
  if runtime_import_paths:
    state["candidate_files"] = runtime_import_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(runtime_import_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_frontend_runtime_import_normalization",
        reason="Generated source imported preview runtime packages that are not installed in the workspace.",
        paths=runtime_import_paths,
      )
      append_step(
        state,
        agent,
        "normalize_frontend_runtime_imports_before_preview",
        {"paths": runtime_import_paths},
        {"status": "normalized", "paths": runtime_import_paths},
      )
  return touched_paths


def visual_qa_failure_reason(visual_qa_result: Any, warnings: Any) -> str:
  result = object_value(visual_qa_result)
  warning_text = "; ".join(str(item) for item in warnings if isinstance(item, str)) if isinstance(warnings, list) else ""
  severity = text_or_default(result.get("severity"), "")
  issues = [item for item in list_value(result.get("layout_issues")) if isinstance(item, dict)]
  if not issues:
    return warning_text

  details: list[str] = []
  for issue in issues[:6]:
    viewport = text_or_default(issue.get("viewport"), "unknown viewport")
    issue_type = text_or_default(issue.get("type"), "layout_issue")
    message = text_or_default(issue.get("message"), "")
    element = object_value(issue.get("element"))
    selector = text_or_default(element.get("selector"), "")
    text = text_or_default(element.get("text"), "")
    target = selector or text[:80]
    detail = f"{viewport}: {issue_type}"
    if target:
      detail = f"{detail} at {target}"
    if message:
      detail = f"{detail} ({message})"
    details.append(detail)
  prefix = warning_text or "Preview layout QA failed."
  severity_text = f" Severity: {severity}." if severity else ""
  return f"{prefix}{severity_text} Layout issues: {' | '.join(details)}"


def interaction_fix_verification_reason(state: dict[str, Any]) -> str:
  prompt = text_or_default(state.get("prompt"), "").lower()
  has_problem_signal = any(term in prompt for term in INTERACTION_PROBLEM_TERMS)
  has_interaction_target = any(term in prompt for term in INTERACTION_TARGET_TERMS)
  if not has_problem_signal or not has_interaction_target:
    return ""
  changed_paths = set(list_value(state.get("changed_file_paths")))
  candidate_files = [
    item
    for item in list_value(state.get("candidate_files"))
    if isinstance(item, dict) and text_or_default(item.get("path"), "") in changed_paths
  ]
  changed_text = "\n".join(text_or_default(item.get("content"), "") for item in candidate_files)
  if any(marker in changed_text for marker in INTERACTION_CODE_MARKERS):
    return ""
  return (
    "Requested interaction/button fix did not add or modify detectable event wiring "
    "(handler, state change, navigation, submit, toggle, or link behavior). "
    "Repair the actual clicked interaction instead of changing only static UI."
  )


def small_scoped_update_static_qa_reason(state: dict[str, Any]) -> str:
  analysis = object_value(state.get("update_analysis"))
  if text_or_default(analysis.get("scope"), "small") != "small":
    return ""
  if text_or_default(analysis.get("update_mode"), "") not in {"targeted_patch", "bug_fix"}:
    return ""
  prompt = text_or_default(state.get("prompt"), "").lower()
  if any(term in prompt for term in VISUAL_QA_REQUIRED_TERMS):
    return ""
  changed_paths = list_value(state.get("changed_file_paths"))
  if len(changed_paths) > 2:
    return ""
  return "Small targeted/bug update verified with static scope checks; browser visual QA skipped for speed."
