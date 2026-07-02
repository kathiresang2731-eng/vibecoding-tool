from __future__ import annotations

import json
import re
from typing import Any

from ..budget_config import AGENT_BUDGETS
from .values import list_value, object_value, text_or_default


def compact_existing_files(files: Any, *, max_content_chars: int = 1200) -> list[dict[str, Any]]:
  compact: list[dict[str, Any]] = []
  if not isinstance(files, list):
    return compact
  for file_item in files:
    if not isinstance(file_item, dict):
      continue
    path = file_item.get("path")
    content = file_item.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
      continue
    compact.append(
      {
        "path": path,
        "content_preview": truncate_for_artifact_prompt(content, max_content_chars),
        "content_chars": len(content),
      }
    )
  return compact


def compact_files_for_prompt(files: Any, *, max_files: int, max_content_chars: int) -> list[dict[str, Any]]:
  return compact_existing_files(list_value(files)[:max_files], max_content_chars=max_content_chars)


def select_update_files_for_prompt(
  files: Any,
  *,
  prompt: str,
  update_analysis: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
  analysis = object_value(update_analysis)
  mode = text_or_default(analysis.get("update_mode"), "feature_patch")
  if mode in {"targeted_patch", "bug_fix"}:
    max_files = AGENT_BUDGETS.targeted_update_files
    max_chars = AGENT_BUDGETS.targeted_update_chars
  elif mode == "feature_patch":
    max_files = AGENT_BUDGETS.feature_update_files
    max_chars = AGENT_BUDGETS.feature_update_chars
  else:
    max_files = AGENT_BUDGETS.ui_update_files
    max_chars = AGENT_BUDGETS.ui_update_chars

  candidates = [item for item in list_value(files) if isinstance(item, dict)]
  preferred_paths = {
    text_or_default(path, "")
    for path in list_value(analysis.get("candidate_files"))
    if text_or_default(path, "")
  }
  for task in list_value(analysis.get("scoped_update_tasks")):
    for path in list_value(object_value(task).get("candidate_files")):
      path_text = text_or_default(path, "")
      if path_text:
        preferred_paths.add(path_text)

  prompt_tokens = {
    token
    for token in re.findall(r"[a-z0-9]+", str(prompt or "").lower())
    if len(token) >= 4
  }

  def score(file_item: dict[str, Any]) -> tuple[int, str]:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "").lower()
    path_key = path.lower()
    path_tokens = {token for token in re.findall(r"[a-z0-9]+", path_key) if len(token) >= 4}
    content_tokens = {token for token in re.findall(r"[a-z0-9]+", content[:4000]) if len(token) >= 4}
    value = 0
    if path in preferred_paths:
      value += 1000
    if path.endswith((".jsx", ".tsx", ".js", ".ts", ".css", ".scss")):
      value += 80
    value += len(prompt_tokens & path_tokens) * 45
    value += min(10, len(prompt_tokens & content_tokens)) * 18
    if any(part in path_key for part in ("node_modules", "dist", "package-lock")):
      value -= 500
    return (-value, path)

  ranked = sorted(candidates, key=score)
  selected: list[dict[str, Any]] = []
  used_chars = 0
  for file_item in ranked:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if not path or not content:
      continue
    remaining = max_chars - used_chars
    if remaining <= 0 or len(selected) >= max_files:
      break
    per_file_limit = max(1200, min(remaining, max_chars // max_files + 1200))
    content_for_prompt = truncate_for_artifact_prompt(content, per_file_limit)
    selected.append(
      {
        "path": path,
        "content": content_for_prompt,
        "content_chars": len(content),
        "included_chars": len(content_for_prompt),
        "truncated": len(content_for_prompt) < len(content),
      }
    )
    used_chars += len(content_for_prompt)

  budget = {
    "mode": mode,
    "max_files": max_files,
    "max_chars": max_chars,
    "selected_file_count": len(selected),
    "selected_chars": used_chars,
    "candidate_file_count": len(candidates),
    "preferred_paths": sorted(preferred_paths),
  }
  return selected, budget


def compact_memories_for_prompt(memories: Any, *, max_items: int, max_content_chars: int) -> list[dict[str, Any]]:
  compact: list[dict[str, Any]] = []
  for item in list_value(memories)[:max_items]:
    if not isinstance(item, dict):
      continue
    content = item.get("content")
    content_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False) if content is not None else ""
    compact.append(
      {
        "namespace": item.get("namespace"),
        "key": item.get("key"),
        "kind": item.get("kind"),
        "content_preview": truncate_for_artifact_prompt(content_text, max_content_chars),
        "content_chars": len(content_text),
        "updated_at": item.get("updated_at"),
      }
    )
  return compact


def json_for_prompt(value: Any, *, max_chars: int) -> str:
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


def compact_prepared_sections_for_artifact(prepared_sections: dict[str, Any]) -> dict[str, Any]:
  compact: dict[str, Any] = {}
  for key, value in list(prepared_sections.items()):
    if key == "dynamic_specialist_results":
      compact[key] = compact_dynamic_specialist_results_for_prompt(value)
    elif key == "dynamic_agent_workflow":
      compact[key] = compact_dynamic_workflow_for_prompt(value)
    else:
      compact[key] = compact_value_for_artifact_prompt(value, max_chars=24_000)
  return compact


def compact_dynamic_workflow_for_prompt(value: Any) -> dict[str, Any]:
  workflow = object_value(value)
  tasks = [
    {
      "id": task.get("id"),
      "capability": task.get("required_capability"),
      "runtime_action": task.get("runtime_action"),
      "dependencies": list_value(task.get("dependencies"))[:6],
      "optional": bool(task.get("optional")),
    }
    for task in list_value(workflow.get("tasks"))
    if isinstance(task, dict)
  ]
  assignments = [
    {
      "task_id": item.get("task_id"),
      "agent_id": item.get("agent_id"),
      "agent_name": item.get("agent_name"),
      "type": item.get("assignment_type"),
      "confidence": item.get("confidence"),
    }
    for item in list_value(workflow.get("assignments"))
    if isinstance(item, dict)
  ]
  return {
    "domain": workflow.get("domain"),
    "scope": workflow.get("scope"),
    "planning_source": workflow.get("planning_source"),
    "tasks": tasks[:18],
    "assignments": assignments[:18],
    "created_agent_ids": list_value(workflow.get("created_agent_ids"))[:8],
    "reused_agent_ids": list_value(workflow.get("reused_agent_ids"))[:12],
    "parallel_groups": list_value(workflow.get("parallel_groups"))[:10],
  }


def compact_dynamic_specialist_results_for_prompt(value: Any) -> dict[str, Any]:
  results = object_value(value)
  compact_results: dict[str, Any] = {}
  for task_id, raw_result in list(object_value(results.get("results")).items()):
    if not isinstance(raw_result, dict):
      continue
    compact_results[text_or_default(task_id, "")] = {
      "agent": raw_result.get("agent"),
      "agent_id": raw_result.get("agent_id"),
      "status": raw_result.get("status"),
      "source": raw_result.get("source"),
      "summary": truncate_for_artifact_prompt(raw_result.get("summary"), 700),
      "recommendations": truncate_list_for_artifact_prompt(raw_result.get("recommendations"), limit=5, max_chars=320),
      "requirements": truncate_list_for_artifact_prompt(raw_result.get("requirements"), limit=5, max_chars=320),
      "risks": truncate_list_for_artifact_prompt(raw_result.get("risks"), limit=3, max_chars=260),
    }
  return {
    "status": results.get("status"),
    "completed_task_ids": list_value(results.get("completed_task_ids"))[:18],
    "parallel_groups_executed": list_value(results.get("parallel_groups_executed"))[:10],
    "candidate_change_summary": object_value(results.get("candidate_change_summary")),
    "dynamic_agent_executions": [
      {
        "task_id": item.get("task_id"),
        "agent_id": item.get("agent_id"),
        "status": item.get("status"),
        "source": item.get("source"),
        "duration_ms": item.get("duration_ms"),
        "execution_failed": bool(item.get("execution_failed")),
        "fallback_reason": truncate_for_artifact_prompt(item.get("fallback_reason"), 240),
      }
      for item in list_value(results.get("dynamic_agent_executions"))
      if isinstance(item, dict)
    ][:18],
    "results": compact_results,
  }


def compact_value_for_artifact_prompt(value: Any, *, max_chars: int) -> Any:
  try:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  except TypeError:
    text = json.dumps(str(value), ensure_ascii=False)
  if len(text) <= max_chars:
    return value
  return {
    "_truncated": True,
    "original_chars": len(text),
    "preview": text[:max_chars],
  }


def truncate_list_for_artifact_prompt(value: Any, *, limit: int, max_chars: int) -> list[str]:
  return [truncate_for_artifact_prompt(item, max_chars) for item in list_value(value)[:limit]]


def truncate_for_artifact_prompt(value: Any, max_chars: int) -> str:
  text = str(value or "").strip()
  if len(text) <= max_chars:
    return text
  return f"{text[: max_chars - 15].rstrip()}... [truncated]"
