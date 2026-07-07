from __future__ import annotations

import re
from typing import Any

from ...artifacts import normalize_artifact_path
try:
  from ...prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block
from ...prompts import build_update_analysis_prompt
from ...prompt_context import current_user_prompt
from ..compaction import compact_memories_for_prompt
from ..constants import (
  SCOPED_UPDATE_MAX_NEW_FILES,
  SCOPED_UPDATE_MAX_TASKS,
  SCOPED_UPDATE_NEW_FILE_EXTENSIONS,
  SCOPED_UPDATE_NEW_FILE_PREFIXES,
)
from ..file_ops import unique_paths
from ..targeted_updates import (
  SUPPORTED_COLOR_NAMES,
  clean_targeted_text_value,
  targeted_text_request,
)
from ..values import list_value, object_value, string_list, text_or_default


def run_update_analysis_agent(
  control_provider: Any,
  prompt: str,
  read_result: dict[str, Any],
  memory_result: dict[str, Any],
  *,
  code_search_matches: list[dict[str, Any]],
  error_diagnosis: dict[str, Any] | None = None,
) -> dict[str, Any]:
  prompt = current_user_prompt(prompt)
  existing_paths = [
    text_or_default(item.get("path"), "")
    for item in list_value(read_result.get("files"))
    if isinstance(item, dict) and text_or_default(item.get("path"), "")
  ]
  try:
    response = control_provider.generate_json(
      build_update_analysis_prompt(
        prompt,
        project_file_index=list_value(read_result.get("file_index")),
        candidate_context=code_search_matches,
        memory_context=compact_memories_for_prompt(memory_result.get("memories", []), max_items=5, max_content_chars=500),
        error_diagnosis=error_diagnosis,
      ),
      system_instruction=(
        "You are the Update Analysis Agent. Return strict JSON only. "
        "Select the smallest safe update path. Never route bounded fixes, UI refinements, "
        "text changes, or bug fixes to full regeneration. "
        f"{prompt_policy_block(include_generation=False, include_update=True)}"
      ),
      trace_label="update_analysis_agent",
    )
  except Exception as exc:
    return {
      "update_mode": "needs_clarification",
      "request_kind": "other",
      "execution_strategy": "clarify",
      "scope": "small",
      "summary": "Update analysis could not safely determine the requested change.",
      "target_symbols": [],
      "candidate_files": [],
      "candidate_new_files": [],
      "required_agents": [],
      "targeted_patch": {"kind": "other"},
      "preserve_rules": ["Preserve every existing project file until the update scope is confirmed."],
      "allow_full_regeneration": False,
      "clarification_question": (
        "I could not safely identify the exact files and change required. "
        "Please describe the specific broken behavior or the exact component, text, or feature to update."
      ),
      "reason": f"Update analysis model failed: {str(exc)[:300]}",
    }
  return normalize_update_analysis(
    response,
    existing_paths=existing_paths,
    code_search_matches=code_search_matches,
    user_prompt=prompt,
    error_diagnosis=error_diagnosis,
  )


def normalized_ui_knowledge_matches(
  code_search_matches: list[dict[str, Any]],
  *,
  existing_path_set: set[str],
) -> list[dict[str, Any]]:
  """Return rendered UI ownership evidence carried by project knowledge.

  This is structural evidence, not routing.  It lets a later LLM/scoped agent
  know where visible text/buttons/headers actually live in the codebase.
  """
  results: list[dict[str, Any]] = []
  seen: set[tuple[str, str, int]] = set()
  for item in code_search_matches:
    if not isinstance(item, dict):
      continue
    path = text_or_default(item.get("path"), "")
    if path not in existing_path_set:
      continue
    if text_or_default(item.get("match_type"), "") != "project_ui_knowledge":
      continue
    ui = object_value(item.get("ui_semantic"))
    line = 0
    try:
      line = int(ui.get("line") or item.get("line_start") or 0)
    except (TypeError, ValueError):
      line = 0
    text = text_or_default(ui.get("text") or " ".join(string_list(item.get("matched_terms"), [])), "")
    key = (path, text.lower(), line)
    if key in seen:
      continue
    seen.add(key)
    results.append(
      {
        "path": path,
        "line": line,
        "component": text_or_default(ui.get("component") or item.get("symbol"), ""),
        "route": text_or_default(ui.get("route"), ""),
        "element_kind": text_or_default(ui.get("element_kind"), ""),
        "text": text,
        "purpose": text_or_default(ui.get("purpose"), ""),
        "event": text_or_default(ui.get("event"), ""),
        "handler": text_or_default(ui.get("handler"), ""),
        "target": text_or_default(ui.get("target"), ""),
        "score": item.get("score", 0.0),
        "snippet": text_or_default((list_value(item.get("snippets")) or [""])[0], "")[:900],
      }
    )
  return results


def infer_prompt_target_label(user_prompt: str) -> str:
  """Extract a destination label from natural language without deciding intent."""
  prompt = text_or_default(user_prompt, "")
  route_match = re.search(r"(#[/][A-Za-z0-9_./-]+|/[A-Za-z0-9_./-]+)", prompt)
  if route_match:
    return route_match.group(1)
  weak_deictic_labels = {"that", "this", "current", "same", "below", "above", "here", "there"}
  candidates: list[tuple[int, str]] = []
  for pattern in (
    r"\b(?:redirect|navigate|open|show|display|land|go)\s+(?:to|into|on)?\s*(?:the\s+)?([A-Za-z][A-Za-z0-9 _&/-]{1,80}?)(?:\s+(?:page|screen|route|module|flow))?\b",
    r"\b(?:to|into)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 _&/-]{1,80}?)(?:\s+(?:page|screen|route|module|flow))\b",
    r"\bon\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 _&/-]{1,80}?)(?:\s+(?:page|screen|route|module|flow))\b",
  ):
    match = re.search(pattern, prompt, flags=re.IGNORECASE)
    if match:
      label = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;")
      normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
      if not normalized or normalized in weak_deictic_labels:
        continue
      score = 20 if pattern.startswith(r"\b(?:redirect") else 5
      candidates.append((score, label[:120]))
  if candidates:
    candidates.sort(key=lambda item: (-item[0], item[1].lower()))
    return candidates[0][1]
  return ""


def interaction_from_ui_knowledge_and_prompt(
  ui_element: dict[str, Any],
  *,
  user_prompt: str,
) -> dict[str, Any]:
  kind = text_or_default(ui_element.get("element_kind"), "element").replace("_", " ")
  text = text_or_default(ui_element.get("text"), "")
  component = text_or_default(ui_element.get("component"), "")
  route = text_or_default(ui_element.get("route"), "")
  target = text_or_default(ui_element.get("target"), "") or infer_prompt_target_label(user_prompt)
  trigger = text_or_default(ui_element.get("event"), "")
  if not trigger and kind in {"button", "link"}:
    trigger = "activate"
  try:
    confidence = float(ui_element.get("score") or 0.0)
  except (TypeError, ValueError):
    confidence = 0.0
  confidence = max(0.65, min(1.0, confidence))
  return {
    "component": (f"{text} {kind}".strip() or component or kind)[:120],
    "trigger": trigger[:120],
    "expected": text_or_default(user_prompt, "")[:240],
    "source_page": (component or route or text_or_default(ui_element.get("path"), ""))[:120],
    "target_page_or_route": target[:160],
    "confidence": confidence,
  }


def normalize_update_analysis(
  response: Any,
  *,
  existing_paths: list[str],
  code_search_matches: list[dict[str, Any]],
  user_prompt: str = "",
  error_diagnosis: dict[str, Any] | None = None,
) -> dict[str, Any]:
  user_prompt = current_user_prompt(user_prompt)
  raw = object_value(response)
  valid_modes = {"targeted_patch", "bug_fix", "feature_patch", "full_regeneration", "needs_clarification"}
  update_mode = text_or_default(raw.get("update_mode"), "needs_clarification")
  if update_mode not in valid_modes:
    update_mode = "needs_clarification"
  scope = text_or_default(raw.get("scope"), "small")
  if scope not in {"small", "medium", "large"}:
    scope = "small"
  deterministic_request_kinds = {
    "brand_name_update",
    "document_title_update",
    "cta_text_update",
    "pagination_page_size_update",
  }
  valid_request_kinds = deterministic_request_kinds | {
    "theme_color_update",
    "bug_fix",
    "feature_patch",
    "full_regeneration",
    "style_reference_update",
    "interaction_wiring_update",
    "other",
  }
  request_kind = text_or_default(raw.get("request_kind"), "other")
  if request_kind not in valid_request_kinds:
    request_kind = "other"
  broad_candidate_limit = 8 if request_kind in {
    "interaction_wiring_update",
    "theme_color_update",
    "style_reference_update",
    "feature_patch",
  } else 4
  targeted_patch = normalize_targeted_patch_intent(raw.get("targeted_patch"), request_kind=request_kind)
  deterministic_patch_ready = (
    update_mode == "targeted_patch"
    and request_kind in deterministic_request_kinds
    and targeted_patch_is_actionable(targeted_patch, request_kind)
  )
  existing_path_set = set(existing_paths)
  candidate_files: list[str] = []
  for raw_path in string_list(raw.get("candidate_files"), []):
    try:
      path = normalize_artifact_path(raw_path)
    except Exception:
      continue
    if path in existing_path_set and path not in candidate_files:
      candidate_files.append(path)
    if len(candidate_files) >= broad_candidate_limit:
      break
  if update_mode in {"targeted_patch", "bug_fix", "feature_patch"} and not candidate_files:
    candidate_files = unique_paths(
      [
        text_or_default(item.get("path"), "")
        for item in code_search_matches
        if isinstance(item, dict) and text_or_default(item.get("path"), "") in existing_path_set
      ]
    )[:broad_candidate_limit]
  diagnosis = object_value(error_diagnosis)
  diagnosis_candidate_files = [
    path
    for path in string_list(diagnosis.get("candidate_files"), [])
    if path in existing_path_set
  ]
  if diagnosis and update_mode in {"bug_fix", "feature_patch", "targeted_patch"}:
    diagnosis_categories = string_list(diagnosis.get("categories"), [])
    error_fix_scope = 2 if any(category in diagnosis_categories for category in {"runtime_exception", "missing_api_route", "data_shape_mismatch", "compile_or_import_error", "database_error"}) else 4
    candidate_files = unique_paths([*diagnosis_candidate_files, *candidate_files])[:error_fix_scope]
    if "runtime_exception" in diagnosis_categories or "missing_api_route" in diagnosis_categories:
      update_mode = "bug_fix"
      request_kind = "bug_fix"
  if update_mode in {"targeted_patch", "bug_fix", "feature_patch"} and not candidate_files and not deterministic_patch_ready:
    update_mode = "needs_clarification"
  feature_plan = normalize_update_feature_plan(raw.get("feature_plan"), user_prompt=user_prompt, raw_analysis=raw, update_mode=update_mode)
  interaction_summary = text_or_default(raw.get("interaction_summary"), "")[:300]
  if not interaction_summary:
    interaction_summary = text_or_default(feature_plan.get("interaction"), "")[:300]
  interaction = normalize_interaction_intent(raw.get("interaction"), feature_plan=feature_plan, interaction_summary=interaction_summary)
  if not interaction_summary and any(interaction.values()):
    interaction_summary = format_interaction_summary(interaction)
  ui_elements = normalized_ui_knowledge_matches(
    code_search_matches,
    existing_path_set=existing_path_set,
  )
  ui_owner_paths = unique_paths(
    [
      text_or_default(item.get("path"), "")
      for item in ui_elements
    ]
  )
  ui_interaction_owner_detected = bool(
    ui_elements
    and update_mode in {"targeted_patch", "bug_fix", "feature_patch"}
    and request_kind in {"other", "bug_fix", "feature_patch"}
    and text_or_default(ui_elements[0].get("element_kind"), "") in {"button", "link", "a"}
  )
  if ui_interaction_owner_detected:
    request_kind = "interaction_wiring_update"
    broad_candidate_limit = max(broad_candidate_limit, 8)
  raw_interaction = object_value(raw.get("interaction"))
  interaction_has_contract = any(
    text_or_default(raw_interaction.get(key), "")
    for key in ("component", "trigger", "expected", "source_page", "target_page_or_route")
  )
  if request_kind == "interaction_wiring_update" and ui_elements and not any(
    text_or_default(interaction.get(key), "")
    for key in ("component", "trigger", "expected", "source_page", "target_page_or_route")
  ):
    interaction = interaction_from_ui_knowledge_and_prompt(
      ui_elements[0],
      user_prompt=user_prompt,
    )
    interaction_summary = format_interaction_summary(interaction)
  if interaction_has_contract or (request_kind == "interaction_wiring_update" and ui_owner_paths):
    # The LLM supplied the semantic contract. Structural UI knowledge only
    # localizes its real owner; it does not decide the intent.
    if request_kind in {"other", "bug_fix", "feature_patch"}:
      request_kind = "interaction_wiring_update"
    candidate_files = unique_paths([*ui_owner_paths, *candidate_files])[:broad_candidate_limit]
  target_files = [
    path
    for path in string_list(raw.get("target_files"), [])
    if path in existing_path_set
  ][:broad_candidate_limit]
  if (interaction_has_contract or request_kind == "interaction_wiring_update") and ui_owner_paths:
    target_files = unique_paths([*ui_owner_paths, *target_files])[:broad_candidate_limit]
  required_agents_by_mode = {
    "targeted_patch": ["scoped_update_agent"],
    "bug_fix": ["debug_patch_agent"],
    "feature_patch": ["feature_patch_agent"],
    "full_regeneration": ["full_dynamic_workflow"],
    "needs_clarification": [],
  }
  allow_full_regeneration = bool(raw.get("allow_full_regeneration")) and update_mode == "full_regeneration"
  if update_mode == "full_regeneration" and not allow_full_regeneration:
    update_mode = "needs_clarification"
  model_execution_strategy = text_or_default(raw.get("execution_strategy"), "")
  if update_mode == "needs_clarification":
    execution_strategy = "clarify"
  elif update_mode == "full_regeneration":
    request_kind = "full_regeneration"
    execution_strategy = "full_dynamic_workflow"
  elif model_execution_strategy == "deterministic_patch" and deterministic_patch_ready:
    execution_strategy = "deterministic_patch"
  else:
    execution_strategy = "scoped_model_patch"
  if execution_strategy == "deterministic_patch":
    required_agents = ["targeted_update_agent"]
  else:
    required_agents = required_agents_by_mode[update_mode]
  candidate_new_files = normalize_scoped_update_candidate_new_files(
    raw.get("candidate_new_files"),
    existing_paths=existing_paths,
    update_mode=update_mode,
  )
  if update_mode == "feature_patch":
    raw_for_inference = {**raw, "feature_plan": feature_plan}
    candidate_new_files = unique_paths(
      [
        *candidate_new_files,
        *infer_scoped_update_candidate_new_files(
          user_prompt,
          raw_analysis=raw_for_inference,
          candidate_files=candidate_files,
          existing_paths=existing_paths,
          code_search_matches=code_search_matches,
        ),
      ]
    )[:SCOPED_UPDATE_MAX_NEW_FILES]
  if existing_list_content_update_request(user_prompt, candidate_files=candidate_files):
    candidate_new_files = []
  new_file_requirements = normalize_new_file_requirements(
    raw.get("new_file_requirements"),
    candidate_new_files=candidate_new_files,
    candidate_files=candidate_files,
    existing_paths=existing_paths,
    feature_plan=feature_plan,
    user_prompt=user_prompt,
  )
  if new_file_requirements["needed"] and "new_file_requirement_agent" not in required_agents:
    required_agents = ["new_file_requirement_agent", *required_agents]
  scoped_update_tasks = normalize_scoped_update_tasks(
    raw.get("scoped_update_tasks") or raw.get("update_tasks") or raw.get("tasks"),
    user_prompt=user_prompt,
    raw_analysis=raw,
    update_mode=update_mode,
    candidate_files=candidate_files,
    candidate_new_files=candidate_new_files,
    existing_paths=existing_paths,
    code_search_matches=code_search_matches,
  )
  return {
    "update_mode": update_mode,
    "request_kind": request_kind,
    "execution_strategy": execution_strategy,
    "scope": scope,
    "summary": text_or_default(raw.get("summary"), "Analyze the requested existing-project update."),
    "target_symbols": string_list(raw.get("target_symbols"), [])[:12],
    "feature_plan": feature_plan,
    "candidate_files": candidate_files,
    "target_files": target_files,
    "reference_files": string_list(raw.get("reference_files"), [])[:4],
    "style_reference_summary": text_or_default(raw.get("style_reference_summary"), "")[:240],
    "interaction_summary": interaction_summary,
    "interaction": interaction,
    "matched_ui_elements": ui_elements[:12],
    "project_ui_match_count": len(ui_elements),
    "project_ui_matched_files": ui_owner_paths[:12],
    "candidate_new_files": candidate_new_files,
    "new_file_requirements": new_file_requirements,
    "scoped_update_tasks": scoped_update_tasks,
    "required_agents": required_agents,
    "targeted_patch": targeted_patch,
    "preserve_rules": string_list(
      raw.get("preserve_rules"),
      [
        "Preserve all unrelated existing files and functionality.",
        "Do not regenerate or redesign the website unless explicitly approved.",
      ],
    )[:12],
    "allow_full_regeneration": allow_full_regeneration,
    "clarification_question": text_or_default(
      raw.get("clarification_question"),
      "Please identify the exact component, behavior, text, or feature that should change.",
    )
    if update_mode == "needs_clarification"
    else "",
    "reason": text_or_default(raw.get("reason"), "Selected the smallest safe update workflow."),
    "error_diagnosis": diagnosis,
  }


def normalize_scoped_update_candidate_new_files(
  value: Any,
  *,
  existing_paths: list[str],
  update_mode: str,
) -> list[str]:
  if update_mode != "feature_patch":
    return []
  existing_path_set = set(existing_paths)
  candidate_new_files: list[str] = []
  for raw_path in string_list(value, []):
    try:
      path = normalize_artifact_path(raw_path)
    except Exception:
      continue
    if not is_safe_scoped_update_new_file_path(path, existing_path_set):
      continue
    if path not in candidate_new_files:
      candidate_new_files.append(path)
    if len(candidate_new_files) >= SCOPED_UPDATE_MAX_NEW_FILES:
      break
  return candidate_new_files


def normalize_new_file_requirements(
  value: Any,
  *,
  candidate_new_files: list[str],
  candidate_files: list[str],
  existing_paths: list[str],
  feature_plan: dict[str, Any],
  user_prompt: str,
) -> dict[str, Any]:
  raw = object_value(value)
  existing_path_set = set(existing_paths)
  candidate_file_set = set(candidate_files)
  planned_files: list[dict[str, Any]] = []
  raw_plans_by_path: dict[str, dict[str, Any]] = {}
  for raw_plan in list_value(raw.get("planned_files")):
    plan = object_value(raw_plan)
    try:
      path = normalize_artifact_path(text_or_default(plan.get("path"), ""))
    except Exception:
      continue
    if path in candidate_new_files:
      raw_plans_by_path[path] = plan
  for path in candidate_new_files:
    plan = raw_plans_by_path.get(path, {})
    integration_file = normalize_integration_file_for_new_file(
      plan.get("integration_file"),
      candidate_files=candidate_files,
    )
    import_name = sanitize_pascal_component_name(plan.get("import_name")) or new_file_import_name(path, feature_plan=feature_plan)
    planned_files.append(
      {
        "path": path,
        "kind": normalize_new_file_kind(plan.get("kind"), path),
        "reason": text_or_default(
          plan.get("reason"),
          new_file_requirement_reason(path, user_prompt=user_prompt),
        )[:300],
        "integration_file": integration_file,
        "import_name": import_name,
        "import_path_from_integration": import_path_from_integration_file(
          integration_file,
          path,
        )
        if integration_file
        else "",
      }
    )
  return {
    "needed": bool(planned_files),
    "reason": text_or_default(
      raw.get("reason"),
      "New files are required to keep the requested feature modular." if planned_files else "Existing files are sufficient for this update.",
    )[:300],
    "planned_files": planned_files,
    "verification": {
      "existing_files_checked": [
        path for path in unique_paths([*candidate_files, *string_list(object_value(raw.get("verification")).get("existing_files_checked"), [])]) if path in existing_path_set
      ][:4],
      "import_or_render_required": bool(planned_files),
      "integration_files_valid": all(item["integration_file"] in candidate_file_set for item in planned_files),
    },
  }


def normalize_new_file_kind(value: Any, path: str) -> str:
  raw = text_or_default(value, "").lower()
  valid = {"component", "page", "helper", "service", "style", "data"}
  if raw in valid:
    return raw
  if path.startswith("src/pages/"):
    return "page"
  if path.startswith("src/utils/"):
    return "helper"
  if path.startswith("src/services/"):
    return "service"
  if path.endswith(".css"):
    return "style"
  if path.endswith(".json"):
    return "data"
  return "component"


def normalize_integration_file_for_new_file(value: Any, *, candidate_files: list[str]) -> str:
  candidate_set = set(candidate_files)
  try:
    path = normalize_artifact_path(text_or_default(value, ""))
  except Exception:
    path = ""
  if path in candidate_set:
    return path
  for candidate in candidate_files:
    if candidate.endswith((".jsx", ".tsx", ".js", ".ts")):
      return candidate
  return candidate_files[0] if candidate_files else ""


def new_file_import_name(path: str, *, feature_plan: dict[str, Any]) -> str:
  planned_name = sanitize_pascal_component_name(feature_plan.get("name"))
  if planned_name:
    return planned_name
  basename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  return sanitize_pascal_component_name(basename) or "GeneratedFeature"


def import_path_from_integration_file(integration_file: str, new_file_path: str) -> str:
  if not integration_file or not new_file_path:
    return ""
  integration_parts = integration_file.split("/")[:-1]
  new_parts = new_file_path.split("/")
  while integration_parts and new_parts and integration_parts[0] == new_parts[0]:
    integration_parts.pop(0)
    new_parts.pop(0)
  prefix = "../" * len(integration_parts)
  relative = f"{prefix}{'/'.join(new_parts)}"
  if not relative.startswith("."):
    relative = f"./{relative}"
  return re.sub(r"\.(jsx|tsx|js|ts)$", "", relative)


def new_file_requirement_reason(path: str, *, user_prompt: str) -> str:
  if path.startswith("src/pages/"):
    return "The requested feature is a page or route-level view and should be isolated in a new page file."
  if path.startswith("src/utils/"):
    return "The requested behavior needs reusable helper logic instead of adding more code to an existing component."
  if path.startswith("src/services/"):
    return "The requested behavior needs service/client logic separated from UI components."
  if "modal" in user_prompt.lower() or "dialog" in user_prompt.lower():
    return "The requested modal/dialog should be isolated as a reusable component and rendered from an existing file."
  return "The requested feature is bounded but large enough to keep as a separate component imported by an existing file."


def format_interaction_summary(interaction: dict[str, str]) -> str:
  component = text_or_default(interaction.get("component"), "")
  trigger = text_or_default(interaction.get("trigger"), "")
  expected = text_or_default(interaction.get("expected"), "")
  target = text_or_default(interaction.get("target_page_or_route"), "")
  if target and target not in expected:
    expected = f"{expected} → {target}".strip(" →")
  if component and trigger and expected:
    return f"{component} ({trigger}): {expected}"[:300]
  if component and expected:
    return f"{component}: {expected}"[:300]
  if component and trigger:
    return f"{component} on {trigger}"[:300]
  return (expected or component or trigger)[:300]


def normalize_interaction_intent(
  value: Any,
  *,
  feature_plan: dict[str, Any] | None = None,
  interaction_summary: str = "",
) -> dict[str, Any]:
  raw = object_value(value)
  plan = object_value(feature_plan)
  component = text_or_default(raw.get("component") or raw.get("element") or raw.get("name"), "")[:120]
  trigger = text_or_default(raw.get("trigger") or raw.get("action"), "")[:120]
  expected = text_or_default(raw.get("expected") or raw.get("behavior") or raw.get("outcome"), "")[:240]
  source_page = text_or_default(
    raw.get("source_page")
    or raw.get("source")
    or raw.get("source_component")
    or raw.get("from_page"),
    "",
  )[:120]
  target_page_or_route = text_or_default(
    raw.get("target_page_or_route")
    or raw.get("target_route")
    or raw.get("target_page")
    or raw.get("destination")
    or raw.get("to_page"),
    "",
  )[:160]
  try:
    confidence = float(raw.get("confidence"))
  except (TypeError, ValueError):
    confidence = 0.0
  if not component:
    component = text_or_default(plan.get("name"), "")[:120]
  if not expected:
    expected = text_or_default(plan.get("interaction") or interaction_summary, "")[:240]
  if confidence <= 0 and (component or trigger or expected or source_page or target_page_or_route):
    confidence = 0.6
  return {
    "component": component,
    "trigger": trigger,
    "expected": expected,
    "source_page": source_page,
    "target_page_or_route": target_page_or_route,
    "confidence": max(0.0, min(1.0, confidence)),
  }


def normalize_update_feature_plan(
  value: Any,
  *,
  user_prompt: str,
  raw_analysis: dict[str, Any],
  update_mode: str,
) -> dict[str, Any]:
  if update_mode not in {"feature_patch", "bug_fix"}:
    return {"name": "", "type": "", "items": [], "interaction": ""}
  raw = object_value(value)
  feature_type = text_or_default(raw.get("type") or raw.get("feature_type"), "")
  if feature_type not in {"component", "page", "panel", "modal", "drawer", "helper", "service", "other"}:
    feature_type = infer_feature_type_from_prompt(user_prompt, raw_analysis)
  items = string_list(raw.get("items") or raw.get("feature_items") or raw.get("sections") or raw.get("tabs"), [])[:12]
  if not items:
    items = scoped_list_items_from_prompt(user_prompt)[:12]
  feature_name = sanitize_pascal_component_name(
    raw.get("name")
    or raw.get("feature_name")
    or raw.get("component_name")
    or raw.get("page_name")
  )
  if not feature_name:
    feature_name = feature_name_from_candidate_new_files(raw_analysis.get("candidate_new_files"))
  return {
    "name": feature_name,
    "type": feature_type,
    "items": items,
    "interaction": text_or_default(raw.get("interaction") or raw.get("trigger") or raw.get("behavior"), "")[:300],
  }


def infer_feature_type_from_prompt(user_prompt: str, raw_analysis: dict[str, Any]) -> str:
  text = " ".join(
    [
      user_prompt,
      text_or_default(raw_analysis.get("summary"), ""),
      " ".join(string_list(raw_analysis.get("target_symbols"), [])),
    ]
  ).lower()
  if any(marker in text for marker in ("modal", "dialog")):
    return "modal"
  if "drawer" in text:
    return "drawer"
  if any(marker in text for marker in ("page", "route", "screen")):
    return "page"
  if any(marker in text for marker in ("panel", "sidebar", "detail", "details", "tab", "tabs")):
    return "panel"
  if any(marker in text for marker in ("helper", "utility", "utils")):
    return "helper"
  if any(marker in text for marker in ("service", "api client", "fetch")):
    return "service"
  return "component"


def sanitize_pascal_component_name(value: Any) -> str:
  if not isinstance(value, str) or not value.strip():
    return ""
  words = re.findall(r"[A-Za-z][A-Za-z0-9]*", value)
  if not words:
    return ""
  name = "".join(pascal_case_feature_word(word) for word in words[:5])
  if not re.fullmatch(r"[A-Z][A-Za-z0-9]{1,79}", name):
    return ""
  generic_names = {
    "App",
    "Component",
    "Feature",
    "FeaturePanel",
    "Module",
    "Page",
    "Panel",
    "Update",
    "Website",
  }
  if name in generic_names:
    return ""
  return name


def feature_name_from_candidate_new_files(value: Any) -> str:
  for raw_path in string_list(value, []):
    try:
      path = normalize_artifact_path(raw_path)
    except Exception:
      continue
    basename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    name = sanitize_pascal_component_name(basename)
    if name:
      return name
  return ""


def normalize_scoped_update_tasks(
  value: Any,
  *,
  user_prompt: str,
  raw_analysis: dict[str, Any],
  update_mode: str,
  candidate_files: list[str],
  candidate_new_files: list[str],
  existing_paths: list[str],
  code_search_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  if update_mode not in {"targeted_patch", "bug_fix", "feature_patch"} or not candidate_files:
    return []
  tasks: list[dict[str, Any]] = []
  for index, raw_task in enumerate(list_value(value)):
    task = normalize_scoped_update_task(
      raw_task,
      index=index,
      fallback_prompt=user_prompt,
      update_mode=update_mode,
      global_candidate_files=candidate_files,
      global_candidate_new_files=candidate_new_files,
      existing_paths=existing_paths,
    )
    if task:
      tasks.append(task)
    if len(tasks) >= SCOPED_UPDATE_MAX_TASKS:
      break
  tasks = [
    task
    for task in tasks
    if scoped_task_relevant_to_user_prompt(task, user_prompt)
  ]
  if len(tasks) <= 1 or not scoped_tasks_cover_prompt_items(tasks, user_prompt):
    inferred_prompts = infer_scoped_update_task_prompts(user_prompt, raw_analysis)
    if len(inferred_prompts) > 1:
      tasks = [
        normalize_scoped_update_task(
          {
            "id": f"step_{index + 1}",
            "summary": task_prompt,
            "prompt": task_prompt,
            "candidate_files": candidate_files_for_scoped_task(
              task_prompt,
              global_candidate_files=candidate_files,
              code_search_matches=code_search_matches,
            ),
            "candidate_new_files": candidate_new_files_for_scoped_task(
              task_prompt,
              global_candidate_new_files=candidate_new_files,
            ),
            "target_symbols": extract_update_search_terms(task_prompt)[:8],
          },
          index=index,
          fallback_prompt=task_prompt,
          update_mode=update_mode,
          global_candidate_files=candidate_files,
          global_candidate_new_files=candidate_new_files,
          existing_paths=existing_paths,
        )
        for index, task_prompt in enumerate(inferred_prompts[:SCOPED_UPDATE_MAX_TASKS])
      ]
      tasks = [task for task in tasks if task]
  if len(tasks) <= 1:
    return []
  return tasks[:SCOPED_UPDATE_MAX_TASKS]


def scoped_task_relevant_to_user_prompt(task: dict[str, Any], user_prompt: str) -> bool:
  user_terms = {
    term.lower()
    for term in extract_update_search_terms(current_user_prompt(user_prompt))
  }
  if not user_terms:
    return True
  task_text = " ".join(
    [
      text_or_default(task.get("summary"), ""),
      text_or_default(task.get("prompt"), ""),
      " ".join(string_list(task.get("target_symbols"), [])),
    ]
  )
  task_terms = {
    term.lower()
    for term in extract_update_search_terms(task_text)
  }
  return bool(user_terms & task_terms)


def existing_list_content_update_request(user_prompt: str, *, candidate_files: list[str]) -> bool:
  lowered = current_user_prompt(user_prompt).lower()
  if not any(marker in lowered for marker in ("add ", "include ", "insert ", "append ", "show ", "display ")):
    return False
  if any(
    marker in lowered
    for marker in (
      "new component",
      "new page",
      "new modal",
      "new drawer",
      "new service",
      "new api",
      "new backend",
    )
  ):
    return False
  return any(
    "/data/" in path.lower()
    or path.lower().endswith(("data.js", "data.ts", "data.jsx", "data.tsx", "mockdata.js", "mock-data.js"))
    for path in candidate_files
  )


def normalize_scoped_update_task(
  raw_task: Any,
  *,
  index: int,
  fallback_prompt: str,
  update_mode: str,
  global_candidate_files: list[str],
  global_candidate_new_files: list[str],
  existing_paths: list[str],
) -> dict[str, Any] | None:
  raw = object_value(raw_task)
  prompt = text_or_default(raw.get("prompt") or raw.get("request") or raw.get("instruction"), fallback_prompt)
  summary = text_or_default(raw.get("summary") or raw.get("name") or raw.get("description"), prompt)
  candidate_files = [
    path
    for path in normalize_existing_candidate_paths(raw.get("candidate_files"), existing_paths=existing_paths)
    if path in set(global_candidate_files)
  ]
  if not candidate_files:
    candidate_files = list(global_candidate_files)
  candidate_new_files = normalize_scoped_update_candidate_new_files(
    raw.get("candidate_new_files"),
    existing_paths=existing_paths,
    update_mode=update_mode,
  )
  if not candidate_new_files and update_mode == "feature_patch":
    candidate_new_files = [
      path
      for path in infer_scoped_update_candidate_new_files(
        prompt,
        raw_analysis={**raw, "summary": summary},
        candidate_files=candidate_files,
        existing_paths=existing_paths,
        code_search_matches=[],
      )
      if path in set(global_candidate_new_files)
    ]
  candidate_new_files = [path for path in candidate_new_files if path in set(global_candidate_new_files)]
  task_id = text_or_default(raw.get("id"), f"step_{index + 1}")
  task_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", task_id).strip("_") or f"step_{index + 1}"
  return {
    "id": task_id[:48],
    "index": index + 1,
    "update_mode": update_mode,
    "summary": summary[:300],
    "prompt": prompt[:1200],
    "candidate_files": candidate_files[:4],
    "candidate_new_files": candidate_new_files[:SCOPED_UPDATE_MAX_NEW_FILES],
    "target_symbols": string_list(raw.get("target_symbols"), extract_update_search_terms(prompt))[:12],
  }


def normalize_existing_candidate_paths(value: Any, *, existing_paths: list[str]) -> list[str]:
  existing_path_set = set(existing_paths)
  paths: list[str] = []
  for raw_path in string_list(value, []):
    try:
      path = normalize_artifact_path(raw_path)
    except Exception:
      continue
    if path in existing_path_set and path not in paths:
      paths.append(path)
  return paths


def infer_scoped_update_task_prompts(user_prompt: str, raw_analysis: dict[str, Any]) -> list[str]:
  candidates = split_scoped_update_prompt(user_prompt)
  if len(candidates) <= 1:
    summary = text_or_default(raw_analysis.get("summary"), "")
    if summary and summary.lower() != user_prompt.lower():
      candidates = split_scoped_update_prompt(summary)
  normalized: list[str] = []
  for candidate in candidates:
    text = candidate.strip(" .;\n\t")
    if len(text) < 8:
      continue
    if not re.search(r"[A-Za-z]", text):
      continue
    if text not in normalized:
      normalized.append(text)
    if len(normalized) >= SCOPED_UPDATE_MAX_TASKS:
      break
  return normalized


def split_scoped_update_prompt(value: str) -> list[str]:
  list_tasks = grouped_list_update_tasks(value)
  if list_tasks:
    return list_tasks
  text = re.sub(r"\s+", " ", value.strip())
  if not text:
    return []
  bullet_parts = [
    part.strip(" -\u20220123456789.)\t")
    for part in re.split(r"(?:\n|\r|;)+", value)
    if part.strip(" -\u20220123456789.)\t")
  ]
  if len(bullet_parts) > 1:
    return bullet_parts
  verb_pattern = r"(?:add|build|create|update|change|fix|show|open|make|implement|include|connect|wire|render|display|enable|support)\b"
  parts = re.split(rf"\s+(?:and|also|plus)\s+(?={verb_pattern})", text, flags=re.IGNORECASE)
  if len(parts) == 1:
    parts = re.split(rf"\s*,\s*(?={verb_pattern})", text, flags=re.IGNORECASE)
  return [part.strip() for part in parts if part.strip()]


def grouped_list_update_tasks(value: str) -> list[str]:
  lines = normalized_prompt_lines(value)
  if len(lines) < 3:
    return []
  preamble = lines[0]
  requested_items = [line for line in lines[1:] if looks_like_scoped_list_item(line)]
  if len(requested_items) < 3:
    return []
  task_items = requested_items[:12]
  tasks = [
    (
      f"{preamble}. Create the clicked contact detail page shell and navigation "
      f"for: {', '.join(task_items)}."
    )
  ]
  max_content_groups = max(1, SCOPED_UPDATE_MAX_TASKS - 1)
  for group in chunk_list_evenly(task_items, max_content_groups):
    if group:
      tasks.append(f"Add sections or tabs for: {', '.join(group)}.")
  return tasks[:SCOPED_UPDATE_MAX_TASKS]


def normalized_prompt_lines(value: str) -> list[str]:
  lines: list[str] = []
  for raw_line in value.replace("\r", "\n").split("\n"):
    line = raw_line.strip()
    if not line:
      continue
    line = re.sub(r"^[-*\u2022\s]*\d*[\).:-]?\s*", "", line).strip()
    if line:
      lines.append(line)
  return lines


def looks_like_scoped_list_item(value: str) -> bool:
  normalized = value.strip(" .;:-")
  if not normalized:
    return False
  words = re.findall(r"\b[A-Za-z][A-Za-z0-9']*\b", normalized.replace("\u2019", "'"))
  if not words or len(words) > 5:
    return False
  update_verbs = {
    "add",
    "build",
    "change",
    "create",
    "fix",
    "implement",
    "make",
    "open",
    "provide",
    "show",
    "update",
  }
  return words[0].lower() not in update_verbs


def chunk_list_evenly(items: list[str], max_groups: int) -> list[list[str]]:
  if max_groups <= 1 or len(items) <= 1:
    return [items]
  group_count = min(max_groups, len(items))
  groups: list[list[str]] = []
  for index in range(group_count):
    start = round(index * len(items) / group_count)
    end = round((index + 1) * len(items) / group_count)
    groups.append(items[start:end])
  return [group for group in groups if group]


def scoped_list_items_from_prompt(value: str) -> list[str]:
  lines = normalized_prompt_lines(value)
  if len(lines) < 3:
    return []
  return [line for line in lines[1:] if looks_like_scoped_list_item(line)]


def scoped_tasks_cover_prompt_items(tasks: list[dict[str, Any]], user_prompt: str) -> bool:
  prompt_items = scoped_list_items_from_prompt(user_prompt)
  if len(prompt_items) < 3:
    return True
  task_text = " ".join(
    " ".join(
      [
        text_or_default(task.get("summary"), ""),
        text_or_default(task.get("prompt"), ""),
        " ".join(string_list(task.get("target_symbols"), [])),
      ]
    ).lower()
    for task in tasks
  )
  for item in prompt_items:
    normalized_item = re.sub(r"[^a-z0-9]+", " ", item.lower().replace("\u2019", "'")).strip()
    if normalized_item and normalized_item not in task_text:
      return False
  return True


def candidate_files_for_scoped_task(
  task_prompt: str,
  *,
  global_candidate_files: list[str],
  code_search_matches: list[dict[str, Any]],
) -> list[str]:
  terms = extract_update_search_terms(task_prompt)
  scored: list[tuple[int, str]] = []
  for path in global_candidate_files:
    score = 0
    lowered_path = path.lower()
    if any(term.lower() in lowered_path for term in terms):
      score += 3
    for match in code_search_matches:
      if not isinstance(match, dict) or text_or_default(match.get("path"), "") != path:
        continue
      matched_terms = [str(term).lower() for term in list_value(match.get("matched_terms"))]
      score += sum(1 for term in terms if term.lower() in matched_terms)
      snippet_text = " ".join(str(snippet).lower() for snippet in list_value(match.get("snippets")))
      score += sum(1 for term in terms if term.lower() in snippet_text)
    if score:
      scored.append((score, path))
  if not scored:
    return global_candidate_files
  return [path for _score, path in sorted(scored, reverse=True)[:4]]


def candidate_new_files_for_scoped_task(
  task_prompt: str,
  *,
  global_candidate_new_files: list[str],
) -> list[str]:
  if not global_candidate_new_files:
    return []
  terms = [term.lower() for term in extract_update_search_terms(task_prompt)]
  matching = [
    path
    for path in global_candidate_new_files
    if any(term and term in path.lower() for term in terms)
  ]
  return matching[:SCOPED_UPDATE_MAX_NEW_FILES]


def infer_scoped_update_candidate_new_files(
  user_prompt: str,
  *,
  raw_analysis: dict[str, Any],
  candidate_files: list[str],
  existing_paths: list[str],
  code_search_matches: list[dict[str, Any]],
) -> list[str]:
  if not should_infer_new_file_for_feature_update(user_prompt, raw_analysis):
    return []
  existing_path_set = set(existing_paths)
  inferred: list[str] = []
  for explicit_path in explicit_new_file_paths_from_prompt(user_prompt):
    if is_safe_scoped_update_new_file_path(explicit_path, existing_path_set):
      inferred.append(explicit_path)
    if len(inferred) >= SCOPED_UPDATE_MAX_NEW_FILES:
      return inferred
  base_name = inferred_feature_component_name(user_prompt, raw_analysis)
  if not base_name:
    return inferred
  folders = inferred_new_file_folders(
    user_prompt,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  extensions = inferred_new_file_extensions(user_prompt)
  for folder in folders:
    for extension in extensions:
      path = f"{folder.rstrip('/')}/{base_name}{extension}"
      if is_safe_scoped_update_new_file_path(path, existing_path_set) and path not in inferred:
        inferred.append(path)
      if len(inferred) >= SCOPED_UPDATE_MAX_NEW_FILES:
        return inferred
  return inferred


def should_infer_new_file_for_feature_update(user_prompt: str, raw_analysis: dict[str, Any]) -> bool:
  prompt_text = " ".join(
    [
      user_prompt,
      text_or_default(raw_analysis.get("summary"), ""),
      " ".join(string_list(raw_analysis.get("target_symbols"), [])),
    ]
  ).lower()
  if not prompt_text.strip():
    return False
  feature_markers = (
    "add",
    "build",
    "create",
    "implement",
    "introduce",
    "new ",
    "open ",
    "show ",
    "support ",
    "widget",
    "modal",
    "dialog",
    "drawer",
    "sidebar",
    "panel",
    "page",
    "view",
    "tab",
    "tabs",
    "form",
    "chart",
    "table",
    "helper",
    "service",
    "detail",
    "details",
  )
  if not any(marker in prompt_text for marker in feature_markers):
    return False
  targeted_only_markers = (
    "rename",
    "change color",
    "background color",
    "theme color",
    "page size",
    "font size",
    "text to",
  )
  return not any(marker in prompt_text for marker in targeted_only_markers)


def explicit_new_file_paths_from_prompt(user_prompt: str) -> list[str]:
  paths: list[str] = []
  for match in re.finditer(r"\b(src|public)/[A-Za-z0-9_./-]+\.(?:jsx|tsx|js|ts|css|json)\b", user_prompt):
    try:
      path = normalize_artifact_path(match.group(0))
    except Exception:
      continue
    if path not in paths:
      paths.append(path)
  return paths[:SCOPED_UPDATE_MAX_NEW_FILES]


def inferred_new_file_folders(
  user_prompt: str,
  *,
  candidate_files: list[str],
  code_search_matches: list[dict[str, Any]],
) -> list[str]:
  lowered = user_prompt.lower()
  if any(marker in lowered for marker in ("helper", "utility", "utils", "format", "parser")):
    preferred = ["src/utils"]
  elif any(marker in lowered for marker in ("service", "api client", "client", "fetch")):
    preferred = ["src/services"]
  elif any(marker in lowered for marker in ("page", "route", "screen")):
    preferred = ["src/pages", "src/components"]
  else:
    preferred = ["src/components"]
  folders = list(preferred)
  source_paths = [
    *candidate_files,
    *[
      text_or_default(item.get("path"), "")
      for item in code_search_matches
      if isinstance(item, dict) and text_or_default(item.get("path"), "")
    ],
  ]
  for path in source_paths:
    if path.startswith("src/components/") and "src/components" not in folders:
      folders.append("src/components")
    elif path.startswith("src/pages/") and "src/pages" not in folders:
      folders.append("src/pages")
    elif path.startswith("src/views/") and "src/views" not in folders:
      folders.append("src/views")
  return folders[:SCOPED_UPDATE_MAX_NEW_FILES]


def inferred_new_file_extensions(user_prompt: str) -> list[str]:
  lowered = user_prompt.lower()
  if "css" in lowered or "style file" in lowered or "stylesheet" in lowered:
    return [".css"]
  if "typescript" in lowered or ".tsx" in lowered:
    return [".tsx"]
  if "helper" in lowered or "utility" in lowered or "service" in lowered:
    return [".js", ".ts"]
  return [".jsx"]


def inferred_feature_component_name(user_prompt: str, raw_analysis: dict[str, Any]) -> str:
  feature_plan_name = sanitize_pascal_component_name(object_value(raw_analysis.get("feature_plan")).get("name"))
  if feature_plan_name:
    return feature_plan_name
  candidate_file_name = feature_name_from_candidate_new_files(raw_analysis.get("candidate_new_files"))
  if candidate_file_name:
    return candidate_file_name
  source = " ".join(
    [
      user_prompt,
      " ".join(string_list(raw_analysis.get("target_symbols"), [])),
      text_or_default(raw_analysis.get("summary"), ""),
    ]
  )
  words = feature_name_words(source)
  if not words:
    return ""
  suffixes = {
    "widget",
    "modal",
    "dialog",
    "drawer",
    "sidebar",
    "panel",
    "page",
    "view",
    "form",
    "chart",
    "table",
    "helper",
    "service",
    "card",
    "list",
  }
  for index, word in enumerate(words):
    if word.lower() in suffixes:
      words = words[: index + 1]
      break
  else:
    if any(word.lower() in {"detail", "details"} for word in words):
      words = words[: words.index(next(word for word in words if word.lower() in {"detail", "details"})) + 1]
      words.append("Panel")
    else:
      words = words[:3]
      words.append("Panel")
  return "".join(pascal_case_feature_word(word) for word in words[:5])


def feature_name_words(source: str) -> list[str]:
  stop_words = {
    "add",
    "also",
    "and",
    "app",
    "application",
    "build",
    "click",
    "clicked",
    "clicking",
    "code",
    "component",
    "components",
    "containing",
    "create",
    "dashboard",
    "existing",
    "feature",
    "file",
    "files",
    "for",
    "from",
    "handle",
    "implement",
    "into",
    "main",
    "make",
    "module",
    "modules",
    "new",
    "open",
    "project",
    "render",
    "rich",
    "section",
    "show",
    "source",
    "support",
    "the",
    "to",
    "update",
    "user",
    "want",
    "we",
    "website",
    "when",
    "with",
  }
  words: list[str] = []
  seen_words: set[str] = set()
  for token in re.findall(r"\b[A-Za-z][A-Za-z0-9]{1,30}\b", source):
    normalized = singular_feature_word(token)
    if normalized.lower() in stop_words:
      continue
    lower_normalized = normalized.lower()
    if lower_normalized not in seen_words:
      words.append(normalized)
      seen_words.add(lower_normalized)
    if len(words) >= 8:
      break
  return words


def singular_feature_word(value: str) -> str:
  lowered = value.lower()
  special = {
    "ai": "AI",
    "crm": "CRM",
    "ui": "UI",
    "ux": "UX",
    "api": "API",
    "contacts": "Contact",
    "customers": "Customer",
    "activities": "Activity",
    "details": "Detail",
    "deals": "Deal",
    "products": "Product",
    "projects": "Project",
    "tabs": "Tab",
  }
  if lowered in special:
    return special[lowered]
  if lowered.endswith("ies") and len(lowered) > 4:
    return value[:-3] + "y"
  if lowered.endswith("s") and not lowered.endswith("ss") and len(value) > 4:
    return value[:-1]
  return value


def pascal_case_feature_word(value: str) -> str:
  if value.isupper() and len(value) <= 4:
    return value
  return value[:1].upper() + value[1:]


def is_safe_scoped_update_new_file_path(path: str, existing_paths: set[str]) -> bool:
  if not path or path in existing_paths:
    return False
  if path.startswith(("/", "./")) or ".." in path.split("/"):
    return False
  if not path.startswith(SCOPED_UPDATE_NEW_FILE_PREFIXES):
    return False
  lowered = path.lower()
  if not lowered.endswith(SCOPED_UPDATE_NEW_FILE_EXTENSIONS):
    return False
  if lowered.startswith(("src/assets/", "public/assets/")):
    return False
  return True


def normalize_targeted_patch_intent(value: Any, *, request_kind: str) -> dict[str, Any]:
  raw = object_value(value)
  kind = text_or_default(raw.get("kind"), request_kind)
  valid_kinds = {
    "brand_name_update",
    "document_title_update",
    "cta_text_update",
    "theme_color_update",
    "pagination_page_size_update",
    "other",
  }
  if kind not in valid_kinds:
    kind = request_kind if request_kind in valid_kinds else "other"
  colors = []
  for raw_color in string_list(raw.get("colors"), []):
    color = raw_color.lower()
    if color in SUPPORTED_COLOR_NAMES and color not in colors:
      colors.append(color)
    if len(colors) >= 4:
      break
  return {
    "kind": kind,
    "old_value": clean_targeted_text_value(text_or_default(raw.get("old_value"), "")),
    "new_value": clean_targeted_text_value(text_or_default(raw.get("new_value"), "")),
    "page_size": normalize_optional_int(raw.get("page_size")),
    "colors": colors,
    "primary_hex": normalize_hex_color(raw.get("primary_hex")),
    "secondary_hex": normalize_hex_color(raw.get("secondary_hex")),
    "accent_hex": normalize_hex_color(raw.get("accent_hex")),
    "background_hex": normalize_hex_color(raw.get("background_hex")),
    "text_hex": normalize_hex_color(raw.get("text_hex")),
    "target_description": text_or_default(raw.get("target_description"), "")[:240],
  }


def targeted_patch_is_actionable(targeted_patch: dict[str, Any], request_kind: str) -> bool:
  kind = text_or_default(targeted_patch.get("kind"), request_kind)
  if kind in {"brand_name_update", "document_title_update", "cta_text_update"}:
    return bool(text_or_default(targeted_patch.get("new_value"), ""))
  if kind == "pagination_page_size_update":
    page_size = normalize_optional_int(targeted_patch.get("page_size"))
    return bool(page_size and 1 <= page_size <= 200)
  if kind == "theme_color_update":
    return bool(
      targeted_patch.get("colors")
      or targeted_patch.get("primary_hex")
      or targeted_patch.get("secondary_hex")
      or targeted_patch.get("accent_hex")
      or targeted_patch.get("background_hex")
      or targeted_patch.get("text_hex")
    )
  return False


def normalize_optional_int(value: Any) -> int | None:
  try:
    integer = int(value)
  except (TypeError, ValueError):
    return None
  return integer


def normalize_hex_color(value: Any) -> str:
  if not isinstance(value, str):
    return ""
  stripped = value.strip()
  if re.fullmatch(r"#[0-9a-fA-F]{6}", stripped):
    return stripped.lower()
  return ""


def targeted_update_request_from_analysis(update_analysis: dict[str, Any]) -> dict[str, Any] | None:
  request_kind = text_or_default(update_analysis.get("request_kind"), "")
  targeted_patch = object_value(update_analysis.get("targeted_patch"))
  kind = text_or_default(targeted_patch.get("kind"), request_kind)
  if kind in {"brand_name_update", "document_title_update", "cta_text_update"}:
    new_value = clean_targeted_text_value(text_or_default(targeted_patch.get("new_value"), ""))
    if not new_value:
      return None
    return targeted_text_request(
      kind,
      new_value,
      old_value=clean_targeted_text_value(text_or_default(targeted_patch.get("old_value"), "")),
    )
  if kind == "pagination_page_size_update":
    page_size = normalize_optional_int(targeted_patch.get("page_size"))
    if page_size is None or page_size < 1 or page_size > 200:
      return None
    return {
      "kind": kind,
      "page_size": page_size,
      "new_value": str(page_size),
      "palette_label": f"{page_size} items per page",
    }
  if kind == "theme_color_update":
    colors = [color for color in string_list(targeted_patch.get("colors"), []) if color in SUPPORTED_COLOR_NAMES]
    primary_hex = normalize_hex_color(targeted_patch.get("primary_hex"))
    secondary_hex = normalize_hex_color(targeted_patch.get("secondary_hex"))
    accent_hex = normalize_hex_color(targeted_patch.get("accent_hex"))
    background_hex = normalize_hex_color(targeted_patch.get("background_hex"))
    text_hex = normalize_hex_color(targeted_patch.get("text_hex"))
    if colors:
      primary = colors[0]
      secondary = colors[1] if len(colors) > 1 else primary
      request = {
        "kind": kind,
        "colors": colors,
        "primary": primary,
        "secondary": secondary,
        "primary_css": primary,
        "secondary_css": secondary,
        "background_css": secondary,
        "text_css": primary,
        "palette_label": " and ".join(unique_paths(colors[:2])),
      }
      for key, value in (
        ("primary_hex", primary_hex),
        ("secondary_hex", secondary_hex),
        ("accent_hex", accent_hex),
        ("background_hex", background_hex),
        ("text_hex", text_hex),
      ):
        if value:
          request[key] = value
      return request
    if primary_hex or secondary_hex or accent_hex or background_hex or text_hex:
      return {
        "kind": kind,
        "colors": [],
        "primary": "custom",
        "secondary": "custom",
        "primary_hex": primary_hex,
        "secondary_hex": secondary_hex,
        "accent_hex": accent_hex,
        "background_hex": background_hex,
        "text_hex": text_hex,
        "primary_css": primary_hex,
        "secondary_css": secondary_hex,
        "accent_css": accent_hex,
        "background_css": background_hex,
        "text_css": text_hex,
        "palette_label": "custom color",
      }
  return None


def build_update_code_search_matches(prompt: str, files: list[dict[str, str]]) -> list[dict[str, Any]]:
  try:
    from ...runtime_config import code_index_enabled
  except ImportError:
    try:
      from backend.agents.runtime_config import code_index_enabled
    except ImportError:
      from agents.runtime_config import code_index_enabled
  if code_index_enabled():
    try:
      from ...code_index.retriever import retrieve_code_context
    except ImportError:
      try:
        from backend.agents.code_index.retriever import retrieve_code_context
      except ImportError:
        from agents.code_index.retriever import retrieve_code_context
    return retrieve_code_context(prompt, files, limit=12)
  terms = extract_update_search_terms(prompt)
  matches: list[dict[str, Any]] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not path.endswith((".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json")):
      continue
    lowered_content = content.lower()
    matched_terms = [term for term in terms if term.lower() in lowered_content or term.lower() in path.lower()]
    if not matched_terms:
      continue
    snippets = []
    for term in matched_terms[:3]:
      snippet = code_match_snippet(content, term)
      if snippet:
        snippets.append(snippet)
    snippets.extend(interaction_render_context_snippets(content, terms=terms))
    matches.append(
      {
        "path": path,
        "matched_terms": matched_terms[:8],
        "snippets": unique_snippets(snippets, max_count=6, max_chars_each=2400),
        "content_chars": len(content),
      }
    )
  return matches[:12]


def extract_update_search_terms(prompt: str) -> list[str]:
  terms: list[str] = []
  patterns = (
    r"\bReferenceError:\s*([A-Za-z_$][\w$]*)",
    r"\b([A-Za-z_$][\w$]*)\s+is\s+not\s+defined\b",
    r"\bCannot\s+find\s+(?:name|module)\s+[\"'`]([^\"'`]+)",
    r"[\"'`]([A-Za-z_$][\w$.-]{2,80})[\"'`]",
  )
  for pattern in patterns:
    for match in re.finditer(pattern, prompt, re.IGNORECASE):
      terms.append(match.group(1))
  stop_words = {
    "above",
    "because",
    "browser",
    "change",
    "error",
    "files",
    "issue",
    "main",
    "opening",
    "product",
    "products",
    "react",
    "request",
    "update",
    "website",
  }
  for token in re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]{3,40}\b", prompt):
    if token.lower() not in stop_words:
      terms.append(token)
  return unique_paths(terms)[:20]


def code_match_snippet(content: str, term: str, *, radius: int = 260) -> str:
  index = content.lower().find(term.lower())
  if index < 0:
    return ""
  start = max(0, index - radius)
  end = min(len(content), index + len(term) + radius)
  return content[start:end]


def interaction_render_context_snippets(content: str, *, terms: list[str]) -> list[str]:
  snippets: list[str] = []
  lowered_terms = [term.lower() for term in terms if isinstance(term, str) and term.strip()]
  patterns = (
    r"\.map\s*\([^)]*=>",
    r"<tr\b",
    r"<tbody\b",
    r"<table\b",
    r"<li\b",
    r"<button\b",
    r"onClick\s*=",
    r"id\s*=\s*['\"]module-[^'\"]+['\"]",
    r"className\s*=\s*['\"][^'\"]*(?:lead|contact|table|row)[^'\"]*['\"]",
  )
  for pattern in patterns:
    for match in re.finditer(pattern, content, flags=re.IGNORECASE | re.DOTALL):
      start = max(0, match.start() - 900)
      end = min(len(content), match.end() + 1400)
      snippet = content[start:end].strip()
      if not snippet:
        continue
      lowered_snippet = snippet.lower()
      if lowered_terms and not any(term in lowered_snippet for term in lowered_terms):
        continue
      snippets.append(snippet)
      if len(snippets) >= 5:
        return snippets
  return snippets


def unique_snippets(snippets: list[str], *, max_count: int, max_chars_each: int) -> list[str]:
  unique: list[str] = []
  seen: set[str] = set()
  for snippet in snippets:
    normalized = snippet.strip()
    if not normalized:
      continue
    if len(normalized) > max_chars_each:
      normalized = normalized[:max_chars_each].rstrip()
    key = re.sub(r"\s+", " ", normalized)
    if key in seen:
      continue
    seen.add(key)
    unique.append(normalized)
    if len(unique) >= max_count:
      break
  return unique
