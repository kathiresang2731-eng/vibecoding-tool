from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any

try:
  from ...runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context
except ImportError:
  from runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context

try:
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
  candidate_files: list[str] = []

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


def _build_code_matches(prompt: str, project_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
  scope_prompt = primary_update_prompt(prompt)
  tool_files = _project_tool_files(project_files)
  if code_index_enabled():
    try:
      from ..code_index.retriever import retrieve_code_context
    except ImportError:
      from agents.code_index.retriever import retrieve_code_context
    return retrieve_code_context(scope_prompt, tool_files, limit=12)
  try:
    from ..agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    from agents.agent_runtime.update_analysis import build_update_code_search_matches
  return build_update_code_search_matches(scope_prompt, tool_files)


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


def _apply_scope_enrichment(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  emit_progress: Any | None = None,
) -> dict[str, Any]:
  enriched = apply_scope_enrichment(analysis, prompt=prompt, project_files=project_files)
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
  if target_files:
    candidates = list(dict.fromkeys([*target_files, *reference_files, *candidates]))[:6]
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
    request_kind=str(analysis.get("request_kind") or "other"),
    target_files=target_files,
    reference_files=reference_files,
    style_reference_snippets=list(analysis.get("style_reference_snippets") or []),
    scope_enrichment_snippets=list(analysis.get("scope_enrichment_snippets") or []),
    enrichment_profile=str(analysis.get("enrichment_profile") or "general_scoped"),
    interaction_summary=str(analysis.get("interaction_summary") or "")[:300],
    interaction={
      "component": str(interaction_raw.get("component") or "")[:120],
      "trigger": str(interaction_raw.get("trigger") or "")[:120],
      "expected": str(interaction_raw.get("expected") or "")[:240],
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
  project_name: str = "",
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
    project_name=project_name,
    project_files=project_files,
  )
  code_matches = _build_code_matches(prompt, project_files)
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
    fallback = _apply_style_reference_scope(fallback, prompt=prompt, project_files=project_files)
    fallback = _apply_scope_enrichment(
      fallback,
      prompt=prompt,
      project_files=project_files,
      emit_progress=emit_progress,
    )
    scope = _analysis_to_scope(
      fallback,
      preflight_source=fallback.get("preflight_source") or "legacy_fallback",
      llm_analysis_used=False,
      code_search_match_count=len(code_matches),
      memory_items_loaded=memory_count,
    )
    _emit_scope_resolved(emit_progress, scope)
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

  if llm_analysis is None:
    fallback = _minimal_code_search_fallback(prompt, project_files)
    fallback = _apply_style_reference_scope(fallback, prompt=prompt, project_files=project_files)
    fallback = _apply_scope_enrichment(
      fallback,
      prompt=prompt,
      project_files=project_files,
      emit_progress=emit_progress,
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

  if not list(llm_analysis.get("candidate_files") or []):
    fallback_candidates = _minimal_code_search_fallback(prompt, project_files)
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
      llm_analysis["scoped_update_tasks"] = _scoped_tasks_from_candidates(
        merged_candidates,
        summary=str(llm_analysis.get("summary") or scope_prompt[:240]),
      )
      if llm_analysis.get("update_mode") == "needs_clarification":
        llm_analysis["update_mode"] = "feature_patch" if len(merged_candidates) >= 2 else "targeted_patch"

  rationale = str(llm_analysis.get("reason") or llm_analysis.get("summary") or "").strip()
  llm_analysis["scope_rationale"] = rationale or f"LLM selected {len(llm_analysis.get('candidate_files') or [])} file(s)."
  llm_analysis["preflight_source"] = "scope_engine_llm"
  llm_analysis = _apply_style_reference_scope(llm_analysis, prompt=prompt, project_files=project_files)
  llm_analysis = _apply_scope_enrichment(
    llm_analysis,
    prompt=prompt,
    project_files=project_files,
    emit_progress=emit_progress,
  )

  scope = _analysis_to_scope(
    llm_analysis,
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    code_search_match_count=len(code_matches),
    memory_items_loaded=memory_count,
  )
  _emit_scope_resolved(emit_progress, scope)
  return scope


def _emit_scope_resolved(emit_progress: Any | None, scope: UpdateScope) -> None:
  if emit_progress is None:
    return
  try:
    emit_progress(
      "scope.resolved",
      f"Update scope: {', '.join(scope.candidate_files[:4]) or 'needs clarification'}",
      status="completed",
      detail={
        "update_mode": scope.update_mode,
        "candidate_files": scope.candidate_files,
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
      },
    )
  except Exception:
    pass
