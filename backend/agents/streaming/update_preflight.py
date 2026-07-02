"""Deterministic + optional LLM update analysis before parallel file workers."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any
try:
  from ...runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context
except ImportError:
  from runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context

try:
  from ..runtime_config import (
    parallel_update_llm_analysis_enabled,
    parallel_update_llm_timeout_seconds,
    parallel_update_preflight_enabled,
  )
except ImportError:
  from agents.runtime_config import (
    parallel_update_llm_analysis_enabled,
    parallel_update_llm_timeout_seconds,
    parallel_update_preflight_enabled,
  )

from .task_planner import (
  _auth_onboarding_flow_paths,
  _mentioned_paths,
  _task_for_path,
  auth_onboarding_flow_repair_summary,
  plan_file_work,
)


def parallel_update_preflight_active(*, intent: str) -> bool:
  return intent == "website_update" and parallel_update_preflight_enabled()


def _project_tool_files(project_files: list[dict[str, Any]]) -> list[dict[str, str]]:
  return [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  ]


def _build_preflight_read_result(project_files: list[dict[str, Any]]) -> dict[str, Any]:
  tool_files = _project_tool_files(project_files)
  return {
    "files": tool_files,
    "file_index": [{"path": item["path"]} for item in tool_files[:120]],
    "file_count": len(tool_files),
  }


def _build_preflight_memory_result(
  *,
  store: Any,
  user: Any,
  project_id: str,
  prompt: str,
  chat_session_id: str | None,
  project_name: str,
  project_files: list[dict[str, Any]],
) -> dict[str, Any]:
  if store is None or user is None or not chat_session_id:
    return {"memories": [], "memory_count": 0}

  memories: list[dict[str, Any]] = []
  try:
    from ..memory.context import build_session_memory_context_block
    from ..memory.episodic import episode_to_memory_row, select_episodic_memories_for_prompt
  except ImportError:
    from agents.memory.context import build_session_memory_context_block
    from agents.memory.episodic import episode_to_memory_row, select_episodic_memories_for_prompt

  session_block = build_session_memory_context_block(store, user, chat_session_id=chat_session_id)
  if session_block.strip():
    memories.append(
      {
        "namespace": "session",
        "kind": "session_state",
        "key": f"session-{str(chat_session_id)[:24]}",
        "content": session_block,
        "metadata_json": {"source": "preflight_session_memory", "chat_session_id": chat_session_id},
      }
    )

  try:
    episodes = select_episodic_memories_for_prompt(
      store,
      user,
      project_id=project_id,
      prompt=prompt,
      chat_session_id=chat_session_id,
      limit=4,
    )
  except Exception:
    episodes = []

  for episode in episodes:
    if not isinstance(episode, dict):
      continue
    row = episode_to_memory_row(episode) if "content" not in episode else episode
    if isinstance(row, dict) and str(row.get("content") or "").strip():
      metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
      metadata = {**metadata, "source": "preflight_episodic_memory"}
      row = {**row, "metadata_json": metadata}
      memories.append(row)

  _ = project_name, project_files
  return {"memories": memories, "memory_count": len(memories)}


def build_heuristic_update_analysis(
  prompt: str,
  project_files: list[dict[str, Any]],
  *,
  max_candidates: int = 4,
) -> dict[str, Any]:
  tool_files = _project_tool_files(project_files)
  existing_paths = [item["path"] for item in tool_files]
  existing_path_set = set(existing_paths)
  files_map = {item["path"]: item["content"] for item in tool_files}

  flow_candidates = _auth_onboarding_flow_paths(prompt, existing_paths, files_map, max_paths=max_candidates)
  if flow_candidates:
    summary = auth_onboarding_flow_repair_summary(prompt)
    update_mode = "bug_fix" if any(
      term in str(prompt or "").lower()
      for term in ("no action", "nothing happens", "not working", "typeerror", "click")
    ) else "feature_patch"
    return {
      "update_mode": update_mode,
      "request_kind": "flow_patch",
      "execution_strategy": "single_grouped_worker",
      "scope": "medium",
      "summary": summary,
      "candidate_files": flow_candidates,
      "candidate_new_files": [],
      "scoped_update_tasks": [
        {
          "id": "analysis-auth-onboarding-flow",
          "summary": summary,
          "candidate_files": flow_candidates,
          "paths": flow_candidates,
          "group_paths": True,
        }
      ],
      "required_agents": ["flow_patch_worker"],
      "preflight_source": "heuristic_auth_onboarding_flow",
    }

  try:
    from ..agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    from agents.agent_runtime.update_analysis import build_update_code_search_matches

  code_matches = build_update_code_search_matches(prompt, tool_files)
  candidate_files: list[str] = []
  for match in code_matches:
    path = str(match.get("path") or "")
    if path in existing_path_set and path not in candidate_files:
      candidate_files.append(path)
    if len(candidate_files) >= max_candidates:
      break

  for path in _mentioned_paths(prompt, existing_paths):
    if path in existing_path_set and path not in candidate_files:
      candidate_files.append(path)
    if len(candidate_files) >= max_candidates:
      break

  if not candidate_files:
    try:
      from .task_planner import resolve_scoped_target_paths
    except ImportError:
      from agents.streaming.task_planner import resolve_scoped_target_paths

    scoped_targets = resolve_scoped_target_paths(
      prompt,
      paths=existing_paths,
      files_map=files_map,
    )
    for path in scoped_targets:
      if path in existing_path_set and path not in candidate_files:
        candidate_files.append(path)
      if len(candidate_files) >= max_candidates:
        break

  if not candidate_files:
    tokens = set(re.findall(r"[a-z0-9]+", str(prompt or "").lower()))
    shell_signals = {
      "dashboard",
      "navbar",
      "header",
      "footer",
      "layout",
      "theme",
      "analytics",
      "sidebar",
      "hero",
    }
    if tokens & shell_signals:
      for path in ("src/App.jsx", "src/pages/Home.jsx", "src/layouts/AppLayout.jsx"):
        if path in existing_path_set and path not in candidate_files:
          candidate_files.append(path)
        if len(candidate_files) >= max_candidates:
          break

  scoped_update_tasks: list[dict[str, Any]] = []
  for path in candidate_files:
    scoped_update_tasks.append(
      {
        "id": f"analysis-{path.replace('/', '-').lower()}",
        "summary": str(prompt or "").strip()[:240],
        "candidate_files": [path],
        "paths": [path],
      }
    )

  update_mode = "feature_patch" if len(candidate_files) >= 2 else "targeted_patch"
  if not candidate_files:
    update_mode = "needs_clarification"

  return {
    "update_mode": update_mode,
    "request_kind": "feature_patch" if len(candidate_files) >= 2 else "other",
    "execution_strategy": "parallel_workers",
    "scope": "small" if len(candidate_files) <= 1 else "medium",
    "summary": str(prompt or "").strip()[:500],
    "candidate_files": candidate_files,
    "candidate_new_files": [],
    "scoped_update_tasks": scoped_update_tasks,
    "required_agents": ["parallel_file_workers"],
    "preflight_source": "heuristic_code_search",
  }


def _scoped_tasks_from_candidates(
  candidate_files: list[str],
  *,
  summary: str,
) -> list[dict[str, Any]]:
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


def merge_preflight_analyses(
  heuristic: dict[str, Any],
  llm: dict[str, Any] | None,
  *,
  preflight_source: str,
) -> dict[str, Any]:
  if not isinstance(llm, dict):
    merged = dict(heuristic)
    merged["preflight_source"] = preflight_source
    return merged

  merged = dict(llm)
  llm_candidates = [str(path) for path in list(merged.get("candidate_files") or []) if path]
  heuristic_candidates = [str(path) for path in list(heuristic.get("candidate_files") or []) if path]
  if not llm_candidates and heuristic_candidates:
    merged["candidate_files"] = heuristic_candidates
  elif llm_candidates and heuristic_candidates:
    merged["candidate_files"] = list(dict.fromkeys([*llm_candidates, *heuristic_candidates]))[:6]

  if not list(merged.get("scoped_update_tasks") or []):
    merged["scoped_update_tasks"] = _scoped_tasks_from_candidates(
      list(merged.get("candidate_files") or []),
      summary=str(merged.get("summary") or heuristic.get("summary") or ""),
    )
  if merged.get("update_mode") == "needs_clarification" and merged.get("candidate_files"):
    merged["update_mode"] = "feature_patch" if len(merged["candidate_files"]) >= 2 else "targeted_patch"

  merged["preflight_source"] = preflight_source
  merged["heuristic_enriched"] = bool(heuristic_candidates)
  return merged


def tasks_from_update_analysis(
  update_analysis: dict[str, Any] | None,
  *,
  max_tasks: int = 5,
) -> list[dict[str, Any]]:
  if not isinstance(update_analysis, dict):
    return []
  tasks: list[dict[str, Any]] = []
  seen_paths: set[str] = set()
  for raw_task in list(update_analysis.get("scoped_update_tasks") or []):
    if not isinstance(raw_task, dict):
      continue
    paths = [str(path) for path in list(raw_task.get("paths") or raw_task.get("candidate_files") or []) if path]
    if raw_task.get("group_paths") and paths:
      grouped_paths = [path for path in paths if path not in seen_paths][:max_tasks]
      for path in grouped_paths:
        seen_paths.add(path)
      summary = str(raw_task.get("summary") or update_analysis.get("summary") or "").strip()
      scope = "update analysis"
      if summary:
        scope = f"update analysis · {summary[:80]}"
      tasks.append(
        {
          "id": f"analysis-group-{'-'.join(path.replace('/', '-').lower() for path in grouped_paths)[:120]}",
          "kind": "file_group",
          "summary": summary[:240],
          "candidate_files": grouped_paths,
          "paths": grouped_paths,
          "scope": scope,
          "depends_on": [],
        }
      )
      if len(tasks) >= max_tasks:
        return tasks
      continue
    for path in paths:
      if path in seen_paths:
        continue
      seen_paths.add(path)
      summary = str(raw_task.get("summary") or update_analysis.get("summary") or "").strip()
      scope = "update analysis"
      if summary:
        scope = f"update analysis · {summary[:80]}"
      tasks.append(_task_for_path(path, scope=scope))
      if len(tasks) >= max_tasks:
        return tasks
  if tasks:
    return tasks

  for path in list(update_analysis.get("candidate_files") or [])[:max_tasks]:
    normalized = str(path or "").strip()
    if not normalized or normalized in seen_paths:
      continue
    seen_paths.add(normalized)
    tasks.append(_task_for_path(normalized, scope="update analysis"))
  return tasks


def format_update_analysis_worker_block(
  update_analysis: dict[str, Any] | None,
  *,
  task: dict[str, Any] | None = None,
) -> str:
  if not isinstance(update_analysis, dict):
    return ""
  lines = [
    "Update analysis (scoped parallel execution):",
    f"- Mode: {update_analysis.get('update_mode') or 'unknown'}",
    f"- Summary: {str(update_analysis.get('summary') or '').strip()[:400]}",
  ]
  preflight_source = str(update_analysis.get("preflight_source") or "").strip()
  if preflight_source:
    lines.append(f"- Preflight source: {preflight_source}")
  candidates = [str(path) for path in list(update_analysis.get("candidate_files") or []) if path]
  if candidates:
    lines.append("- Candidate files: " + ", ".join(candidates[:6]))
  if isinstance(task, dict):
    allowed = [str(path) for path in list(task.get("paths") or []) if path]
    if allowed:
      lines.append(f"- Your assigned path(s): {', '.join(allowed)}")
  return "\n".join(line for line in lines if line.strip())


def _run_llm_update_analysis_with_timeout(
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
    return run_update_analysis_agent(
      control_provider,
      prompt,
      read_result,
      memory_result,
      code_search_matches=code_matches,
    )

  with ThreadPoolExecutor(max_workers=1, thread_name_prefix="worktual-update-preflight") as pool:
    future = submit_with_runtime_context(pool, _call)
    try:
      result = future.result(timeout=max(1, timeout_seconds))
    except FuturesTimeoutError:
      return None
    except Exception:
      raise_if_runtime_cancelled()
      return None
  return result if isinstance(result, dict) else None


def run_parallel_update_preflight(
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  control_provider: Any | None = None,
  read_result: dict[str, Any] | None = None,
  memory_result: dict[str, Any] | None = None,
  store: Any | None = None,
  user: Any | None = None,
  project_id: str = "",
  chat_session_id: str | None = None,
  project_name: str = "",
  emit_progress: Any | None = None,
) -> dict[str, Any]:
  try:
    from ..runtime_config import unified_update_engine_enabled
    from ..update_engine.scope_engine import resolve_update_scope
  except ImportError:
    from agents.runtime_config import unified_update_engine_enabled
    from agents.update_engine.scope_engine import resolve_update_scope

  if unified_update_engine_enabled():
    scope = resolve_update_scope(
      prompt=prompt,
      project_files=project_files,
      control_provider=control_provider,
      store=store,
      user=user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      project_name=project_name,
      emit_progress=emit_progress,
    )
    return scope.to_preflight_payload()

  heuristic = build_heuristic_update_analysis(prompt, project_files)
  read_payload = read_result if isinstance(read_result, dict) else _build_preflight_read_result(project_files)
  memory_payload = memory_result if isinstance(memory_result, dict) else _build_preflight_memory_result(
    store=store,
    user=user,
    project_id=project_id,
    prompt=prompt,
    chat_session_id=chat_session_id,
    project_name=project_name,
    project_files=project_files,
  )

  if not parallel_update_llm_analysis_enabled() or control_provider is None:
    return {
      "update_analysis": heuristic,
      "preflight_source": heuristic.get("preflight_source") or "heuristic_code_search",
      "code_search_match_count": len(heuristic.get("candidate_files") or []),
      "memory_items_loaded": int(memory_payload.get("memory_count") or 0),
      "llm_analysis_used": False,
    }

  try:
    from ..agent_runtime.update_analysis import build_update_code_search_matches
  except ImportError:
    from agents.agent_runtime.update_analysis import build_update_code_search_matches

  code_matches = build_update_code_search_matches(prompt, _project_tool_files(project_files))
  timeout_seconds = parallel_update_llm_timeout_seconds()
  llm_analysis = _run_llm_update_analysis_with_timeout(
    control_provider=control_provider,
    prompt=prompt,
    read_result=read_payload,
    memory_result=memory_payload,
    code_matches=code_matches,
    timeout_seconds=timeout_seconds,
  )

  if llm_analysis is None:
    fallback = merge_preflight_analyses(
      heuristic,
      None,
      preflight_source="heuristic_llm_timeout_fallback",
    )
    return {
      "update_analysis": fallback,
      "preflight_source": "heuristic_llm_timeout_fallback",
      "code_search_match_count": len(code_matches),
      "memory_items_loaded": int(memory_payload.get("memory_count") or 0),
      "llm_analysis_used": False,
      "llm_timeout_seconds": timeout_seconds,
    }

  merged = merge_preflight_analyses(
    heuristic,
    llm_analysis,
    preflight_source="llm_update_analysis_agent",
  )
  return {
    "update_analysis": merged,
    "preflight_source": merged.get("preflight_source") or "llm_update_analysis_agent",
    "code_search_match_count": len(code_matches),
    "memory_items_loaded": int(memory_payload.get("memory_count") or 0),
    "llm_analysis_used": True,
    "llm_timeout_seconds": timeout_seconds,
  }


def plan_file_work_with_update_preflight(
  prompt: str,
  *,
  intent: str,
  project_files: list[dict[str, Any]],
  update_analysis: dict[str, Any] | None = None,
  max_tasks: int = 5,
) -> dict[str, Any]:
  work_plan = plan_file_work(prompt, intent=intent, project_files=project_files, max_tasks=max_tasks)
  analysis_tasks = tasks_from_update_analysis(update_analysis, max_tasks=max_tasks)
  if intent == "website_update" and analysis_tasks:
    work_plan["tasks"] = analysis_tasks
    work_plan["task_count"] = len(analysis_tasks)
    work_plan["planning_source"] = "update_preflight_tasks"
    work_plan["scoped_targets"] = [
      str(path)
      for task in analysis_tasks
      for path in (task.get("paths") or [])
      if str(path or "").strip()
    ]
    from .task_planner import _build_waves, _parallel_worker_waves, _resolve_wave_path_overlaps, _should_use_parallel_workers

    files_map = {
      str(item.get("path") or ""): str(item.get("content") or "")
      for item in project_files
      if isinstance(item, dict) and item.get("path")
    }
    task_by_id = {task["id"]: task for task in analysis_tasks}
    parallel_module = len(analysis_tasks) >= 2
    waves = _resolve_wave_path_overlaps(
      _build_waves(analysis_tasks, files_map, parallel_module=parallel_module),
      task_by_id,
    )
    work_plan["waves"] = waves
    work_plan["wave_count"] = len(waves)
    work_plan["parallel_waves"] = _parallel_worker_waves(waves)
    work_plan["use_parallel_workers"] = _should_use_parallel_workers(tasks=analysis_tasks, waves=waves)
  if isinstance(update_analysis, dict):
    work_plan["update_analysis"] = update_analysis
  return work_plan
