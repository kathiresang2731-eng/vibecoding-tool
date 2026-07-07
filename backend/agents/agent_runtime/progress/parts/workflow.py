from __future__ import annotations

from typing import Any

from backend.agents.artifacts import normalize_generated_file_code
from ...file_ops import tool_files_to_artifact_files
from ...values import list_value, object_value, text_or_default


def normalize_candidate_react_imports(files: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
  normalized_files: list[dict[str, str]] = []
  changed_paths: list[str] = []
  for file_item in files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    normalized_content = normalize_generated_file_code(path, content)
    if normalized_content != content:
      changed_paths.append(path)
    normalized_files.append({"path": path, "content": normalized_content})
  return normalized_files, changed_paths


def sync_generated_website_files_from_candidates(state: dict[str, Any]) -> None:
  generated_website = object_value(state.get("generated_website"))
  candidate_files = list(state.get("candidate_files") or [])
  changed_paths = [file_item["path"] for file_item in candidate_files if isinstance(file_item, dict) and file_item.get("path")]
  if generated_website:
    generated_website["files"] = tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_paths)
    state["generated_website"] = generated_website
    state["files"] = generated_website["files"]


def workflow_progress_detail(workflow_plan: dict[str, Any]) -> dict[str, Any]:
  tasks = [
    {
      "id": text_or_default(task.get("id"), ""),
      "name": text_or_default(task.get("name"), text_or_default(task.get("id"), "Task")),
      "capability": text_or_default(task.get("required_capability"), ""),
      "phase": text_or_default(task.get("execution_phase"), ""),
      "risk": text_or_default(task.get("risk_level"), ""),
      "agent": text_or_default(task.get("agent_id"), ""),
    }
    for task in list_value(workflow_plan.get("tasks"))
    if isinstance(task, dict)
  ]
  assignments = [
    {
      "task_id": text_or_default(item.get("task_id"), ""),
      "agent_id": text_or_default(item.get("agent_id"), ""),
      "reused": bool(item.get("reused")),
      "created": bool(item.get("created")),
      "confidence": item.get("confidence"),
      "reason": text_or_default(item.get("reason"), ""),
    }
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  ]
  return {
    "kind": "workflow_plan",
    "domain": workflow_plan.get("domain"),
    "scope": workflow_plan.get("scope"),
    "task_count": len(tasks),
    "active_agent_count": len(list_value(workflow_plan.get("active_agents"))),
    "created_agent_ids": list_value(workflow_plan.get("created_agent_ids")),
    "reused_agent_ids": list_value(workflow_plan.get("reused_agent_ids")),
    "parallel_groups": list_value(workflow_plan.get("parallel_groups")),
    "tasks": tasks[:16],
    "assignments": assignments[:16],
  }


def website_plan_progress_detail(plan: dict[str, Any], workflow_plan: dict[str, Any] | None = None) -> dict[str, Any]:
  sections = [str(item) for item in list_value(plan.get("sections")) if str(item).strip()]
  quality_checks = [str(item) for item in list_value(plan.get("quality_checks")) if str(item).strip()]
  files_to_change = [str(item) for item in list_value(plan.get("files_to_change")) if str(item).strip()]
  detail = {
    "kind": "website_plan",
    "operation": plan.get("operation"),
    "layout_strategy": plan.get("layout_strategy"),
    "update_strategy": plan.get("update_strategy"),
    "sections": sections[:12],
    "quality_checks": quality_checks[:12],
    "files_to_change": files_to_change[:12],
  }
  if workflow_plan:
    detail["workflow"] = workflow_progress_detail(workflow_plan)
  return detail
