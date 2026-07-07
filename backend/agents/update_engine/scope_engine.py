from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

try:
  from ...runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context
except ImportError:
  from runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context

try:
  from ..code_locations import source_symbol_for_line
  from ..chat_history import primary_update_prompt
  from ..runtime_config import (
    code_index_enabled,
    parallel_update_llm_timeout_seconds,
    unified_update_engine_enabled,
  )
  from .contracts import UpdateScope
  from .intent_parser import merge_style_reference_into_analysis, parse_style_reference_intent
  from .memory_router import build_scope_memory_payload
  from .scope_enrichment import apply_scope_enrichment
except ImportError:
  from agents.code_locations import source_symbol_for_line
  from agents.chat_history import primary_update_prompt
  from agents.runtime_config import (
    code_index_enabled,
    parallel_update_llm_timeout_seconds,
    unified_update_engine_enabled,
  )
  from agents.update_engine.contracts import UpdateScope
  from agents.update_engine.intent_parser import merge_style_reference_into_analysis, parse_style_reference_intent
  from agents.update_engine.memory_router import build_scope_memory_payload
  from agents.update_engine.scope_enrichment import apply_scope_enrichment


def _project_tool_files(project_files: list[dict[str, Any]]) -> list[dict[str, str]]:
  return [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  ]


def _build_read_result(project_files: list[dict[str, Any]]) -> dict[str, Any]:
  tool_files = _project_tool_files(project_files)
  return {
    "files": tool_files,
    "file_index": [{"path": item["path"]} for item in tool_files[:120]],
    "file_count": len(tool_files),
  }


def _scoped_tasks_from_candidates(candidate_files: list[str], *, summary: str) -> list[dict[str, Any]]:
  tasks: list[dict[str, Any]] = []
  for path in candidate_files:
    tasks.append(
      {
        "id": f"analysis-{path.replace('/', '-').lower()}",
        "summary": summary[:240],
        "candidate_files": [path],
        "paths": [path],
      }
    )
  return tasks


def _minimal_code_search_fallback(
  prompt: str,
  project_files: list[dict[str, Any]],
  *,
  max_candidates: int = 4,
) -> dict[str, Any]:
  """Index/memory fallback only — no per-issue keyword routers."""
  scope_prompt = primary_update_prompt(prompt)
  tool_files = _project_tool_files(project_files)
  existing_paths = [item["path"] for item in tool_files]
  existing_path_set = set(existing_paths)
  files_map = {item["path"]: item["content"] for item in tool_files}
  candidate_files: list[str] = []

  try:
    from ..streaming.task_planner import _auth_onboarding_flow_paths
  except ImportError:
    from agents.streaming.task_planner import _auth_onboarding_flow_paths
  flow_paths = _auth_onboarding_flow_paths(scope_prompt, existing_paths, files_map, max_paths=max_candidates)
  if flow_paths:
    candidate_files.extend(path for path in flow_paths if path in existing_path_set)

  if code_index_enabled():
    try:
      from ..code_index.retriever import retrieve_code_context
    except ImportError:
      from agents.code_index.retriever import retrieve_code_context
    matches = retrieve_code_context(scope_prompt, tool_files, limit=max_candidates)
    for match in matches:
      path = str(match.get("path") or "")
      if path in existing_path_set and path not in candidate_files:
        candidate_files.append(path)

  if not candidate_files:
    try:
      from ..agent_runtime.update_analysis import build_update_code_search_matches
    except ImportError:
      from agents.agent_runtime.update_analysis import build_update_code_search_matches
    for match in build_update_code_search_matches(scope_prompt, tool_files):
      path = str(match.get("path") or "")
      if path in existing_path_set and path not in candidate_files:
        candidate_files.append(path)
      if len(candidate_files) >= max_candidates:
        break

  try:
    from ..streaming.task_planner import _mentioned_paths
  except ImportError:
    from agents.streaming.task_planner import _mentioned_paths
  for path in _mentioned_paths(scope_prompt, existing_paths):
    if path in existing_path_set and path not in candidate_files:
      candidate_files.append(path)
    if len(candidate_files) >= max_candidates:
      break

  update_mode = "feature_patch" if len(candidate_files) >= 2 else "targeted_patch"
  if not candidate_files:
    update_mode = "needs_clarification"

  summary = scope_prompt[:500]
  rationale = (
    f"LLM scope analysis unavailable; selected {len(candidate_files)} file(s) from code search and path mentions."
  )
  return {
    "update_mode": update_mode,
    "request_kind": "flow_patch" if flow_paths else "other",
    "candidate_files": candidate_files,
    "candidate_new_files": [],
    "summary": summary,
    "scope_rationale": rationale,
    "scoped_update_tasks": _scoped_tasks_from_candidates(candidate_files, summary=summary),
    "preflight_source": "scope_engine_code_search_fallback",
    "clarification_question": (
      "I could not confidently determine which files to edit. "
      "Please name the page or component to change and the expected behavior."
      if not candidate_files
      else None
    ),
  }


def _new_files_not_required(reason: str) -> dict[str, Any]:
  return {
    "needed": False,
    "reason": reason[:300],
    "planned_files": [],
    "verification": {
      "existing_files_checked": [],
      "import_or_render_required": False,
      "integration_files_valid": True,
    },
  }


def _normalize_flow_patch_existing_file_scope(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
) -> dict[str, Any]:
  """Expand only an LLM-selected multi-page flow patch.

  Mentioning a destination page must not convert a bounded interaction repair
  into a global auth/onboarding/dashboard rewrite.
  """
  request_kind = str(analysis.get("request_kind") or "").strip().lower()
  if request_kind != "flow_patch":
    return analysis
  tool_files = _project_tool_files(project_files)
  existing_paths = [item["path"] for item in tool_files]
  files_map = {item["path"]: item["content"] for item in tool_files}
  try:
    from ..streaming.task_planner import (
      _auth_onboarding_flow_paths,
      auth_onboarding_flow_repair_summary,
    )
  except ImportError:
    from agents.streaming.task_planner import (
      _auth_onboarding_flow_paths,
      auth_onboarding_flow_repair_summary,
    )
  flow_paths = _auth_onboarding_flow_paths(
    prompt,
    existing_paths,
    files_map,
    max_paths=8,
  )
  if not flow_paths:
    return analysis

  merged = dict(analysis)
  existing_path_set = set(existing_paths)
  existing_candidates = [
    str(path)
    for path in list(merged.get("candidate_files") or [])
    if str(path or "") in existing_path_set
  ]
  merged_candidates = list(dict.fromkeys([*flow_paths, *existing_candidates]))[:8]
  merged["request_kind"] = "flow_patch"
  merged["update_mode"] = "feature_patch"
  merged["candidate_files"] = merged_candidates
  merged["target_files"] = list(dict.fromkeys([*flow_paths, *[p for p in list(merged.get("target_files") or []) if p in flow_paths]]))
  merged["candidate_new_files"] = []
  merged["new_file_requirements"] = _new_files_not_required(
    "Existing auth, onboarding, dashboard, and routing files are present; patch those files instead of inventing a new flow wrapper."
  )
  summary = str(merged.get("summary") or auth_onboarding_flow_repair_summary(prompt))
  merged["summary"] = summary
  merged["scope_rationale"] = str(
    merged.get("scope_rationale")
    or "Selected existing auth, onboarding, dashboard, and route/gate files required for the requested flow."
  )
  merged["scoped_update_tasks"] = [
    {
      "id": "auth-onboarding-flow",
      "summary": summary[:240],
      "candidate_files": list(flow_paths),
      "paths": list(flow_paths),
      "candidate_new_files": [],
      "group_paths": True,
    }
  ]
  return merged


def _run_llm_scope_analysis(
  *,
  control_provider: Any,
  prompt: str,
  read_result: dict[str, Any],
  memory_result: dict[str, Any],
  code_matches: list[dict[str, Any]],
  timeout_seconds: int,
) -> dict[str, Any] | None:
  try:
    from ..agent_runtime.update_analysis import run_update_analysis_agent
  except ImportError:
    from agents.agent_runtime.update_analysis import run_update_analysis_agent

  def _call() -> dict[str, Any]:
    raise_if_runtime_cancelled()
    return run_update_analysis_agent(
      control_provider,
      prompt,
      read_result,
      memory_result,
      code_search_matches=code_matches,
    )

  with ThreadPoolExecutor(max_workers=1) as pool:
    future = submit_with_runtime_context(pool, _call)
    try:
      result = future.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
      return None
    except Exception:
      raise_if_runtime_cancelled()
      return None
  return result if isinstance(result, dict) else None


def _build_code_matches(
  prompt: str,
  project_files: list[dict[str, Any]],
  *,
  store: Any = None,
  user: Any = None,
  project_id: str = "",
) -> list[dict[str, Any]]:
  scope_prompt = primary_update_prompt(prompt)
  tool_files = _project_tool_files(project_files)
  try:
    from ..memory.project_knowledge import (
      project_ui_matches_as_code_context,
      select_project_ui_knowledge,
    )
  except ImportError:
    from agents.memory.project_knowledge import (
      project_ui_matches_as_code_context,
      select_project_ui_knowledge,
    )
  ui_matches = select_project_ui_knowledge(
    prompt=scope_prompt,
    files=project_files,
    store=store,
    user=user,
    project_id=project_id,
    limit=24,
  )
  semantic_context = project_ui_matches_as_code_context(ui_matches)
  if code_index_enabled():
    try:
      from ..code_index.retriever import retrieve_code_context
    except ImportError:
      from agents.code_index.retriever import retrieve_code_context
    code_context = retrieve_code_context(scope_prompt, tool_files, project_id=project_id, limit=12)
    return _merge_code_context(semantic_context, code_context)
  try:
    from ..agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    from agents.agent_runtime.update_analysis import build_update_code_search_matches
  return _merge_code_context(
    semantic_context,
    build_update_code_search_matches(scope_prompt, tool_files),
  )


def _merge_code_context(
  semantic_context: list[dict[str, Any]],
  code_context: list[dict[str, Any]],
  *,
  limit: int = 24,
) -> list[dict[str, Any]]:
  """Keep exact rendered-element ownership ahead of coarse file matches."""
  merged: list[dict[str, Any]] = []
  seen: set[tuple[str, str]] = set()
  for item in [*semantic_context, *code_context]:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "")
    match_type = str(item.get("match_type") or "code")
    key = (path, match_type)
    if not path or key in seen:
      continue
    seen.add(key)
    merged.append(item)
    if len(merged) >= limit:
      break
  return merged


def _apply_style_reference_scope(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
) -> dict[str, Any]:
  tool_files = _project_tool_files(project_files)
  paths = [item["path"] for item in tool_files]
  files_map = {item["path"]: item["content"] for item in tool_files}
  style_intent = parse_style_reference_intent(prompt, paths=paths, files_map=files_map)
  if style_intent is None:
    return analysis
  return merge_style_reference_into_analysis(analysis, style_intent, files_map=files_map)


def _search_terms_for_interaction(prompt: str) -> list[str]:
  try:
    from ..agent_runtime.update_analysis import extract_update_search_terms
  except ImportError:
    from agents.agent_runtime.update_analysis import extract_update_search_terms
  return [str(term).strip().lower() for term in extract_update_search_terms(prompt) if str(term).strip()]


def _interaction_code_match_score(match: dict[str, Any], *, terms: list[str]) -> int:
  path = str(match.get("path") or "")
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return 0
  match_type = str(match.get("match_type") or "")
  matched_terms = " ".join(str(term).lower() for term in list(match.get("matched_terms") or []))
  snippet_text = " ".join(str(snippet).lower() for snippet in list(match.get("snippets") or []))
  haystack = " ".join([path.lower(), matched_terms, snippet_text])
  score = 0
  for term in terms:
    if not term:
      continue
    if term in matched_terms:
      score += 8
    if term in snippet_text:
      score += 5
    if term in path.lower():
      score += 2
  if match_type == "project_ui_knowledge":
    score += 45
  if any(signal in snippet_text for signal in ("onclick", "<button", "alert(", "window.alert", "toast", "popup", "modal", "dialog")):
    score += 24
  if "/pages/" in path.lower():
    score += 8
  return score


def _rank_interaction_code_anchor_paths(
  *,
  prompt: str,
  code_matches: list[dict[str, Any]],
  existing_path_set: set[str],
  limit: int = 8,
) -> list[str]:
  terms = _search_terms_for_interaction(prompt)
  scored: list[tuple[int, str]] = []
  for match in code_matches:
    if not isinstance(match, dict):
      continue
    path = str(match.get("path") or "")
    if path not in existing_path_set:
      continue
    score = _interaction_code_match_score(match, terms=terms)
    if score > 0:
      scored.append((score, path))
  scored.sort(key=lambda item: (-item[0], item[1]))
  ranked: list[str] = []
  for _score, path in scored:
    if path not in ranked:
      ranked.append(path)
    if len(ranked) >= limit:
      break
  return ranked


def _apply_interaction_anchor_scope(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  code_matches: list[dict[str, Any]],
) -> dict[str, Any]:
  """Use real code/UI anchors to constrain interaction updates before patching."""
  request_kind = str(analysis.get("request_kind") or "").strip().lower()
  if request_kind != "interaction_wiring_update":
    return analysis
  existing_path_set = {
    str(item.get("path") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }
  anchor_paths = _rank_interaction_code_anchor_paths(
    prompt=prompt,
    code_matches=code_matches,
    existing_path_set=existing_path_set,
  )
  merged = dict(analysis)
  current_candidates = [
    str(path)
    for path in list(merged.get("candidate_files") or [])
    if str(path or "") in existing_path_set
  ]
  current_targets = [
    str(path)
    for path in list(merged.get("target_files") or [])
    if str(path or "") in existing_path_set
  ]
  if anchor_paths:
    merged["candidate_files"] = list(dict.fromkeys([*anchor_paths, *current_targets, *current_candidates]))[:8]
    merged["target_files"] = list(dict.fromkeys([*anchor_paths, *current_targets]))[:8]
    summary = str(merged.get("summary") or primary_update_prompt(prompt) or "Repair requested UI interaction")
    merged["scoped_update_tasks"] = [
      {
        "id": "interaction-anchored-repair",
        "kind": "interaction_wiring",
        "summary": summary[:240],
        "prompt": (
          "Repair the requested interaction using these real source anchors. "
          "Patch the existing handler/modal/state wiring in the approved files; do not invent a replacement component."
        ),
        "candidate_files": list(merged["candidate_files"]),
        "paths": list(merged["candidate_files"]),
        "candidate_new_files": [],
        "group_paths": True,
      }
    ]
    merged["scope_rationale"] = (
      "Interaction update scope was anchored to source/UI matches from the current project before patching. "
      f"Anchors: {', '.join(anchor_paths[:4])}."
    )
  # Interaction repairs should patch the existing owner first. A model-invented
  # candidate_new_file becomes a hard requirement later, so keep new files only
  # when the user explicitly named a concrete path.
  explicit_new_paths = [
    path
    for path in list(merged.get("candidate_new_files") or [])
    if path and str(path) in primary_update_prompt(prompt)
  ]
  merged["candidate_new_files"] = explicit_new_paths
  if not explicit_new_paths:
    merged["new_file_requirements"] = _new_files_not_required(
      "Interaction/modal updates must patch the existing UI owner first; no explicit new file path was requested."
    )
  return merged


def _apply_resolved_target_scope(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  target_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """Keep same-topic resolved targets from widening back into unrelated flows."""
  resolution = target_resolution if isinstance(target_resolution, dict) else {}
  resolved_files = [
    str(path).strip()
    for path in list(resolution.get("resolved_files") or [])
    if str(path).strip()
  ]
  if not resolved_files:
    return analysis

  existing_path_set = {
    str(item.get("path") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }
  resolved_files = [path for path in resolved_files if path in existing_path_set]
  if not resolved_files:
    return analysis

  resolved_button = str(resolution.get("resolved_button") or "").strip()
  resolved_page = str(resolution.get("resolved_page") or "").strip()
  primary_prompt = primary_update_prompt(prompt).lower()
  interaction_issue = any(
    marker in primary_prompt
    for marker in (
      "button",
      "click",
      "onclick",
      "not working",
      "does not work",
      "doesn't work",
      "nothing happens",
      "no action",
      "popup",
      "modal",
      "dialog",
      "redirect",
      "navigate",
      "open",
      "close",
    )
  )
  if not resolved_button and not interaction_issue:
    return analysis

  merged = dict(analysis)
  current_targets = [
    str(path)
    for path in list(merged.get("target_files") or [])
    if str(path or "") in existing_path_set
  ]
  current_candidates = [
    str(path)
    for path in list(merged.get("candidate_files") or [])
    if str(path or "") in existing_path_set
  ]
  same_owner_candidates = [
    path
    for path in current_candidates
    if path in resolved_files
  ]
  focused_candidates = list(dict.fromkeys([*resolved_files, *same_owner_candidates]))[:4]

  request_kind = str(merged.get("request_kind") or "").strip().lower()
  if request_kind in {"other", "feature_patch", "flow_patch", "bug_fix", ""}:
    merged["request_kind"] = "interaction_wiring_update"
  merged["update_mode"] = "bug_fix" if interaction_issue else "targeted_patch"
  merged["candidate_files"] = focused_candidates or resolved_files[:4]
  merged["target_files"] = list(resolved_files[:4])
  merged["reference_files"] = [
    str(path)
    for path in list(merged.get("reference_files") or [])
    if str(path or "") in set(resolved_files)
  ][:4]
  merged["candidate_new_files"] = []
  merged["new_file_requirements"] = _new_files_not_required(
    "A live page/control target was already resolved from same-topic memory and project anchors; patch that existing owner first."
  )
  summary = str(merged.get("summary") or primary_update_prompt(prompt) or "Repair requested UI interaction")
  merged["summary"] = summary
  merged["interaction"] = {
    **(merged.get("interaction") if isinstance(merged.get("interaction"), dict) else {}),
    "component": resolved_button or resolved_page or "resolved target",
    "trigger": "click" if interaction_issue else str((merged.get("interaction") or {}).get("trigger") or ""),
    "source_page": resolved_page,
    "expected": str((merged.get("interaction") or {}).get("expected") or primary_update_prompt(prompt)[:240]),
  }
  merged["interaction_summary"] = (
    str(merged.get("interaction_summary") or "").strip()
    or f"Patch the existing interaction for {resolved_button or resolved_page or resolved_files[0]} in {resolved_files[0]}."
  )
  merged["scoped_update_tasks"] = [
    {
      "id": "resolved-target-interaction-repair",
      "kind": "interaction_wiring",
      "summary": summary[:240],
      "prompt": (
        "The active page/control was already resolved from same-topic conversation memory and live UI anchors. "
        "Patch the existing handler/state wiring in the resolved owner file first."
      ),
      "candidate_files": list(merged["candidate_files"]),
      "paths": list(merged["candidate_files"]),
      "candidate_new_files": [],
      "group_paths": True,
    }
  ]
  merged["scope_rationale"] = (
    "Resolved target scope guard kept the update pinned to the same-topic live owner. "
    f"Page: {resolved_page or 'unknown'}; button: {resolved_button or 'not specified'}; files: {', '.join(resolved_files)}."
  )
  return merged


VISUAL_STYLE_REQUEST_KINDS = {"theme_color_update", "style_reference_update"}


def _is_visual_style_update(analysis: dict[str, Any]) -> bool:
  request_kind = str(analysis.get("request_kind") or "").strip().lower()
  return request_kind in VISUAL_STYLE_REQUEST_KINDS


def _visual_style_path_score(path: str, current_candidates: set[str]) -> int:
  lowered_path = path.lower()
  basename = lowered_path.rsplit("/", 1)[-1]
  if not path or any(part in lowered_path.split("/") for part in {"node_modules", "dist", "build", ".git"}):
    return -10000
  if basename in {"package-lock.json"}:
    return -10000
  if "/data/" in lowered_path or basename in {"mockdata.js", "mock-data.js", "data.js", "data.ts"}:
    return -500

  score = 0
  if path in current_candidates:
    score += 180
  if lowered_path in {
    "src/theme/tokens.js",
    "src/theme/tokens.ts",
    "src/theme.css",
    "src/index.css",
    "src/styles.css",
    "style.css",
    "styles.css",
  }:
    score += 1000
  if basename.startswith("tailwind.config"):
    score += 620
  if lowered_path in {"src/app.jsx", "src/app.tsx"}:
    score += 760
  if lowered_path in {"src/main.jsx", "src/main.tsx"}:
    score += 260
  if "/pages/" in lowered_path:
    score += 520
  if "/components/" in lowered_path:
    score += 420
  if any(part in lowered_path for part in ("layout", "sidebar", "navbar", "header", "shell", "theme")):
    score += 360
  if path.endswith((".css", ".scss", ".sass", ".less")):
    score += 700
  return score


def _visual_style_support_path(path: str) -> bool:
  lowered_path = path.lower()
  basename = lowered_path.rsplit("/", 1)[-1]
  return (
    lowered_path in {
      "src/theme/tokens.js",
      "src/theme/tokens.ts",
      "src/theme.css",
      "src/index.css",
      "src/styles.css",
      "style.css",
      "styles.css",
    }
    or basename.startswith("tailwind.config")
    or lowered_path.endswith((".css", ".scss", ".sass", ".less"))
  )


def _theme_style_tasks(candidate_files: list[str], *, summary: str) -> list[dict[str, Any]]:
  tasks: list[dict[str, Any]] = []
  group_size = 5
  groups = [candidate_files[index : index + group_size] for index in range(0, len(candidate_files), group_size)][:3]
  for index, paths in enumerate(groups, start=1):
    label = ", ".join(paths)
    tasks.append(
      {
        "id": f"visual-style-group-{index}",
        "kind": "visual_style_group",
        "summary": summary[:240],
        "prompt": (
          f"Apply the requested visual theme/style update across this assigned file group: {label}. "
          "Analyze the current file content and update only the real source code needed in these files. "
          "Do not use backend/static color mappings; preserve unrelated layout, copy, data, and behavior."
        ),
        "candidate_files": paths,
        "paths": paths,
        "group_paths": True,
        "target_symbols": ["theme", "style", "palette", "visual design"],
      }
    )
  return tasks


def _apply_theme_color_scope(
  analysis: dict[str, Any],
  *,
  project_files: list[dict[str, Any]],
  prompt: str = "",
) -> dict[str, Any]:
  merged = dict(analysis)
  if not _is_visual_style_update(merged):
    return merged

  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }
  existing_path_set = set(files_map)
  current_candidates = [str(path) for path in list(merged.get("candidate_files") or []) if path]
  current_set = set(current_candidates)

  scored_paths = [
    (path, _visual_style_path_score(path, current_set))
    for path in files_map
    if path in existing_path_set
  ]
  scored_paths.sort(key=lambda item: (-item[1], item[0]))
  visual_candidates = [path for path, score in scored_paths if score > 0]
  safe_current_candidates = [
    path
    for path in current_candidates
    if path in files_map and _visual_style_path_score(path, current_set) > 0
  ]
  style_support_candidates = [path for path in visual_candidates if _visual_style_support_path(path)]
  final_candidates = list(dict.fromkeys([*style_support_candidates, *safe_current_candidates]))[:15]
  if not final_candidates:
    return merged

  summary = str(merged.get("summary") or primary_update_prompt(prompt) or "Apply visual theme/style update")
  merged["request_kind"] = "theme_color_update" if str(merged.get("request_kind") or "") in {"", "other"} else merged.get("request_kind")
  merged["execution_strategy"] = "scoped_model_patch"
  if str(merged.get("update_mode") or "targeted_patch") == "targeted_patch" and len(final_candidates) > 1:
    merged["update_mode"] = "feature_patch"
  merged["candidate_files"] = final_candidates
  merged["target_files"] = final_candidates
  merged["reference_files"] = list(
    dict.fromkeys(
      [
        *(
          str(path)
          for path in list(merged.get("reference_files") or [])
          if path
          and str(path) in final_candidates
          and _visual_style_path_score(str(path), current_set) > 0
        ),
        *[path for path in safe_current_candidates if path in final_candidates],
      ]
    )
  )[:8]
  merged["scoped_update_tasks"] = _theme_style_tasks(final_candidates, summary=summary)
  preserve_rules = [
    str(rule)
    for rule in list(merged.get("preserve_rules") or [])
    if str(rule).strip()
  ]
  merged["preserve_rules"] = list(
    dict.fromkeys(
      [
        *preserve_rules,
        "Do not use backend static color mappings; inspect and patch the actual source files.",
        "Preserve page structure, routes, data, text, and behavior unless the user explicitly requested changing them.",
        "If another rendered file owns visible old styling, request internal scope expansion with the exact path.",
      ]
    )
  )
  merged["scope_rationale"] = (
    "Visual theme/style updates use the scoped code-writing agent with shared style files plus rendered "
    "page/component files that contain current visual classes or inline styles."
  )
  return merged


def _apply_scope_enrichment(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  emit_progress: Any | None = None,
) -> dict[str, Any]:
  enriched = apply_scope_enrichment(analysis, prompt=prompt, project_files=project_files)
  ui_elements = [
    item
    for item in list(enriched.get("matched_ui_elements") or [])
    if isinstance(item, dict)
  ][:20]
  if ui_elements:
    snippets = list(enriched.get("scope_enrichment_snippets") or [])
    existing_keys = {
      (str(item.get("path") or ""), str(item.get("snippet") or "")[:240])
      for item in snippets
      if isinstance(item, dict)
    }
    for item in ui_elements:
      path = str(item.get("path") or "")
      snippet = str(item.get("snippet") or "")
      text = str(item.get("text") or "")
      if not path:
        continue
      evidence = (
        f"UI knowledge: kind={item.get('element_kind') or '-'} "
        f"text={text!r} component={item.get('component') or '-'} "
        f"route={item.get('route') or '-'} line={item.get('line') or '-'} "
        f"purpose={item.get('purpose') or '-'} handler={item.get('handler') or '-'} "
        f"target={item.get('target') or '-'}\n"
        f"{snippet[:900]}"
      ).strip()
      key = (path, evidence[:240])
      if evidence and key not in existing_keys:
        snippets.append({"path": path, "snippet": evidence, "kind": "ui_knowledge"})
        existing_keys.add(key)
    enriched["scope_enrichment_snippets"] = snippets[:18]
  if emit_progress is not None:
    try:
      snippets = list(enriched.get("scope_enrichment_snippets") or [])
      emit_progress(
        "scope.enrichment.completed",
        f"Pre-loaded {len(snippets)} code snippet(s) for scoped update",
        status="completed",
        detail={
          "enrichment_profile": str(enriched.get("enrichment_profile") or ""),
          "snippet_count": len(snippets),
          "paths": list(dict.fromkeys(str(item.get("path") or "") for item in snippets if item.get("path")))[:6],
          "interaction_summary": str(enriched.get("interaction_summary") or "")[:240],
          "project_ui_match_count": int(enriched.get("project_ui_match_count") or len(ui_elements)),
          "project_ui_matched_files": list(enriched.get("project_ui_matched_files") or [])[:8],
        },
      )
    except Exception:
      pass
  return enriched


def _analysis_to_scope(
  analysis: dict[str, Any],
  *,
  preflight_source: str,
  llm_analysis_used: bool,
  code_search_match_count: int,
  memory_items_loaded: int,
) -> UpdateScope:
  candidates = [str(path) for path in list(analysis.get("candidate_files") or []) if path]
  target_files = [str(path) for path in list(analysis.get("target_files") or []) if path]
  reference_files = [str(path) for path in list(analysis.get("reference_files") or []) if path]
  request_kind = str(analysis.get("request_kind") or "other")
  enrichment_profile = str(analysis.get("enrichment_profile") or "general_scoped")
  if request_kind in VISUAL_STYLE_REQUEST_KINDS:
    max_candidates = 15
  elif request_kind in {"flow_patch", "interaction_wiring_update"} or enrichment_profile == "interaction_wiring":
    max_candidates = 8
  else:
    max_candidates = 6
  if target_files:
    candidates = list(dict.fromkeys([*target_files, *reference_files, *candidates]))[:max_candidates]
  tasks = list(analysis.get("scoped_update_tasks") or [])
  if not tasks and candidates:
    tasks = _scoped_tasks_from_candidates(candidates, summary=str(analysis.get("summary") or ""))
  rationale = str(
    analysis.get("scope_rationale")
    or analysis.get("reason")
    or analysis.get("summary")
    or ""
  ).strip()
  interaction_raw = analysis.get("interaction") if isinstance(analysis.get("interaction"), dict) else {}
  return UpdateScope(
    update_mode=str(analysis.get("update_mode") or "targeted_patch"),
    candidate_files=candidates,
    candidate_new_files=[str(path) for path in list(analysis.get("candidate_new_files") or []) if path],
    summary=str(analysis.get("summary") or "").strip()[:500],
    scope_rationale=rationale[:800],
    scoped_update_tasks=tasks,
    preflight_source=preflight_source,
    llm_analysis_used=llm_analysis_used,
    code_search_match_count=code_search_match_count,
    memory_items_loaded=memory_items_loaded,
    clarification_question=str(analysis.get("clarification_question") or "").strip() or None,
    request_kind=request_kind,
    target_files=target_files,
    reference_files=reference_files,
    style_reference_snippets=list(analysis.get("style_reference_snippets") or []),
    scope_enrichment_snippets=list(analysis.get("scope_enrichment_snippets") or []),
    enrichment_profile=enrichment_profile,
    interaction_summary=str(analysis.get("interaction_summary") or "")[:300],
    interaction={
      "component": str(interaction_raw.get("component") or "")[:120],
      "trigger": str(interaction_raw.get("trigger") or "")[:120],
      "expected": str(interaction_raw.get("expected") or "")[:240],
      "source_page": str(interaction_raw.get("source_page") or "")[:120],
      "target_page_or_route": str(interaction_raw.get("target_page_or_route") or "")[:160],
      "confidence": interaction_raw.get("confidence", 0.0),
    },
    raw_analysis=analysis,
  )


def resolve_update_scope(
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  control_provider: Any | None = None,
  store: Any | None = None,
  user: Any | None = None,
  project_id: str = "",
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  target_resolution: dict[str, Any] | None = None,
  emit_progress: Any | None = None,
) -> UpdateScope:
  """Single authority for update file routing: memory + code retrieval + LLM analysis."""
  scope_prompt = primary_update_prompt(prompt)
  read_payload = _build_read_result(project_files)
  memory_payload = build_scope_memory_payload(
    store=store,
    user=user,
    project_id=project_id,
    prompt=prompt,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    project_files=project_files,
  )
  code_matches = _build_code_matches(
    prompt,
    project_files,
    store=store,
    user=user,
    project_id=project_id,
  )
  memory_count = int(memory_payload.get("memory_count") or 0)

  if emit_progress is not None:
    try:
      emit_progress(
        "scope.resolving",
        "Resolving update scope from memory and codebase context",
        status="running",
        detail={
          "scope_prompt_chars": len(scope_prompt),
          "code_match_count": len(code_matches),
          "memory_items": memory_count,
        },
      )
    except Exception:
      pass

  if not unified_update_engine_enabled() or control_provider is None:
    fallback = _minimal_code_search_fallback(prompt, project_files)
    fallback = _normalize_flow_patch_existing_file_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
    )
    fallback = _apply_theme_color_scope(fallback, project_files=project_files, prompt=prompt)
    fallback = _apply_style_reference_scope(fallback, prompt=prompt, project_files=project_files)
    fallback = _apply_interaction_anchor_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
      code_matches=code_matches,
    )
    fallback = _apply_scope_enrichment(
      fallback,
      prompt=prompt,
      project_files=project_files,
      emit_progress=emit_progress,
    )
    fallback = _apply_resolved_target_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
      target_resolution=target_resolution,
    )
    scope = _analysis_to_scope(
      fallback,
      preflight_source=fallback.get("preflight_source") or "legacy_fallback",
      llm_analysis_used=False,
      code_search_match_count=len(code_matches),
      memory_items_loaded=memory_count,
    )
    _emit_scope_resolved(emit_progress, scope, project_files=project_files)
    return scope

  timeout_seconds = parallel_update_llm_timeout_seconds()
  llm_analysis = _run_llm_scope_analysis(
    control_provider=control_provider,
    prompt=scope_prompt,
    read_result=read_payload,
    memory_result=memory_payload,
    code_matches=code_matches,
    timeout_seconds=timeout_seconds,
  )
  deterministic_baseline = _minimal_code_search_fallback(prompt, project_files)

  if llm_analysis is None:
    fallback = deterministic_baseline
    fallback = _normalize_flow_patch_existing_file_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
    )
    fallback = _apply_theme_color_scope(fallback, project_files=project_files, prompt=prompt)
    fallback = _apply_style_reference_scope(fallback, prompt=prompt, project_files=project_files)
    fallback = _apply_interaction_anchor_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
      code_matches=code_matches,
    )
    fallback = _apply_scope_enrichment(
      fallback,
      prompt=prompt,
      project_files=project_files,
      emit_progress=emit_progress,
    )
    fallback = _apply_resolved_target_scope(
      fallback,
      prompt=prompt,
      project_files=project_files,
      target_resolution=target_resolution,
    )
    if fallback.get("candidate_files") and llm_analysis is None:
      fallback["scope_rationale"] = (
        f"LLM scope timed out after {timeout_seconds}s; using code search matches."
      )
    scope = _analysis_to_scope(
      fallback,
      preflight_source="scope_engine_llm_timeout_fallback",
      llm_analysis_used=False,
      code_search_match_count=len(code_matches),
      memory_items_loaded=memory_count,
    )
    _emit_scope_resolved(emit_progress, scope)
    return scope

  if (
    not list(llm_analysis.get("candidate_files") or [])
    or deterministic_baseline.get("request_kind") == "flow_patch"
  ):
    fallback_candidates = deterministic_baseline
    fallback_candidates = _apply_style_reference_scope(fallback_candidates, prompt=prompt, project_files=project_files)
    merged_candidates = list(
      dict.fromkeys(
        [
          *(str(p) for p in list(llm_analysis.get("candidate_files") or []) if p),
          *(fallback_candidates.get("candidate_files") or []),
        ]
      )
    )[:6]
    if merged_candidates:
      llm_analysis["candidate_files"] = merged_candidates
      baseline_tasks = list(fallback_candidates.get("scoped_update_tasks") or [])
      llm_analysis["scoped_update_tasks"] = baseline_tasks or _scoped_tasks_from_candidates(
        merged_candidates,
        summary=str(llm_analysis.get("summary") or scope_prompt[:240]),
      )
      if llm_analysis.get("update_mode") == "needs_clarification":
        llm_analysis["update_mode"] = "feature_patch" if len(merged_candidates) >= 2 else "targeted_patch"
      if fallback_candidates.get("request_kind") == "flow_patch":
        llm_analysis["request_kind"] = "flow_patch"
        llm_analysis["update_mode"] = "feature_patch"
        llm_analysis["summary"] = str(
          fallback_candidates.get("summary") or llm_analysis.get("summary") or ""
        )

  rationale = str(llm_analysis.get("reason") or llm_analysis.get("summary") or "").strip()
  llm_analysis["scope_rationale"] = rationale or f"LLM selected {len(llm_analysis.get('candidate_files') or [])} file(s)."
  llm_analysis["preflight_source"] = "scope_engine_llm"
  llm_analysis = _normalize_flow_patch_existing_file_scope(
    llm_analysis,
    prompt=prompt,
    project_files=project_files,
  )
  llm_analysis = _apply_theme_color_scope(llm_analysis, project_files=project_files, prompt=prompt)
  llm_analysis = _apply_style_reference_scope(llm_analysis, prompt=prompt, project_files=project_files)
  llm_analysis = _apply_interaction_anchor_scope(
    llm_analysis,
    prompt=prompt,
    project_files=project_files,
    code_matches=code_matches,
  )
  llm_analysis = _apply_scope_enrichment(
    llm_analysis,
    prompt=prompt,
    project_files=project_files,
    emit_progress=emit_progress,
  )
  llm_analysis = _apply_resolved_target_scope(
    llm_analysis,
    prompt=prompt,
    project_files=project_files,
    target_resolution=target_resolution,
  )

  scope = _analysis_to_scope(
    llm_analysis,
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    code_search_match_count=len(code_matches),
    memory_items_loaded=memory_count,
  )
  _emit_scope_resolved(emit_progress, scope, project_files=project_files)
  return scope


def _scope_modification_targets(
  scope: UpdateScope,
  *,
  project_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }
  raw_analysis = scope.raw_analysis if isinstance(scope.raw_analysis, dict) else {}
  matched_ui_elements = [
    item
    for item in list(raw_analysis.get("matched_ui_elements") or [])
    if isinstance(item, dict) and str(item.get("path") or "") in files_map
  ]
  ui_by_path: dict[str, list[dict[str, Any]]] = {}
  for item in matched_ui_elements:
    ui_by_path.setdefault(str(item.get("path") or ""), []).append(item)

  targets: list[dict[str, Any]] = []
  seen_paths: set[str] = set()
  for path in list(dict.fromkeys([*scope.candidate_files, *scope.target_files])):
    if path in seen_paths:
      continue
    seen_paths.add(path)
    content = files_map.get(path, "")
    ui_item = (ui_by_path.get(path) or [{}])[0]
    try:
      ui_line = int(ui_item.get("line") or 0)
    except (TypeError, ValueError):
      ui_line = 0
    symbol = source_symbol_for_line(content, ui_line or 1)
    function_name = str(ui_item.get("component") or symbol.get("function_name") or "").strip()
    function_line = ui_line or symbol.get("function_line") or 1
    element_text = str(ui_item.get("text") or "").strip()
    element_kind = str(ui_item.get("element_kind") or "").strip()
    reason = (
      f"matched rendered {element_kind or 'UI'}: {element_text}"
      if element_text
      else str(scope.scope_rationale or scope.request_kind or "selected update candidate")[:220]
    )
    targets.append(
      {
        "path": path,
        "function_name": function_name,
        "function_line": function_line,
        "line": function_line,
        "element_kind": element_kind,
        "text": element_text,
        "reason": reason[:260],
      }
    )
  return targets[:16]


def _emit_scope_resolved(emit_progress: Any | None, scope: UpdateScope, *, project_files: list[dict[str, Any]]) -> None:
  if emit_progress is None:
    return
  modification_targets = _scope_modification_targets(scope, project_files=project_files)
  try:
    emit_progress(
      "scope.resolved",
      f"Update scope: {', '.join(scope.candidate_files[:4]) or 'needs clarification'}",
      status="completed",
      detail={
        "update_mode": scope.update_mode,
        "candidate_files": scope.candidate_files,
        "candidate_new_files": scope.candidate_new_files,
        "target_files": scope.target_files,
        "reference_files": scope.reference_files,
        "request_kind": scope.request_kind,
        "scope_rationale": scope.scope_rationale,
        "preflight_source": scope.preflight_source,
        "llm_analysis_used": scope.llm_analysis_used,
        "style_reference_snippets": scope.style_reference_snippets,
        "scope_enrichment_snippets": scope.scope_enrichment_snippets,
        "enrichment_profile": scope.enrichment_profile,
        "interaction_summary": scope.interaction_summary,
        "interaction": scope.interaction,
        "modification_targets": modification_targets,
        "project_ui_match_count": int(scope.raw_analysis.get("project_ui_match_count") or 0)
        if isinstance(scope.raw_analysis, dict)
        else 0,
        "project_ui_matched_files": list(scope.raw_analysis.get("project_ui_matched_files") or [])[:12]
        if isinstance(scope.raw_analysis, dict)
        else [],
        "matched_ui_elements": list(scope.raw_analysis.get("matched_ui_elements") or [])[:12]
        if isinstance(scope.raw_analysis, dict)
        else [],
      },
    )
  except Exception:
    pass
