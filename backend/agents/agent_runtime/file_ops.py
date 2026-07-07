from __future__ import annotations

from typing import Any

from ..artifacts import normalize_artifact_path, normalize_generated_file_code
from .values import text_or_default


def artifact_files_to_tool_files(files: list[dict[str, Any]]) -> list[dict[str, str]]:
  return [
    {
      "path": str(file_item["path"]),
      "content": str(file_item.get("code") if file_item.get("code") is not None else file_item.get("content", "")),
    }
    for file_item in files
  ]


def merge_candidate_files_for_operation(
  *,
  operation: str,
  read_result: dict[str, Any],
  changed_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  if operation != "update":
    return changed_files
  previous_files = project_files_to_tool_files(read_result.get("files"))
  return merge_project_file_changes(previous_files, changed_files)


def merge_project_file_changes(
  previous_files: list[dict[str, str]],
  changed_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  merged_by_path = {file_item["path"]: file_item["content"] for file_item in previous_files}
  previous_order = [file_item["path"] for file_item in previous_files]
  for file_item in changed_files:
    path = file_item["path"]
    if path not in merged_by_path:
      previous_order.append(path)
    merged_by_path[path] = file_item["content"]
  return [{"path": path, "content": merged_by_path[path]} for path in previous_order if path in merged_by_path]


def integrate_dynamic_candidate_changes(
  candidate_files: list[dict[str, Any]],
  candidate_changes: list[dict[str, Any]],
) -> dict[str, Any]:
  merged_by_path = {
    text_or_default(item.get("path"), ""): text_or_default(item.get("content"), "")
    for item in candidate_files
    if isinstance(item, dict) and text_or_default(item.get("path"), "")
  }
  ordered_paths = list(merged_by_path)
  integrated_paths: list[str] = []
  rejected_conflicts: list[dict[str, Any]] = []
  seen_changes: set[str] = set()
  for change in candidate_changes:
    if not isinstance(change, dict):
      continue
    try:
      path = normalize_artifact_path(text_or_default(change.get("path"), ""))
    except Exception as exc:
      rejected_conflicts.append({"path": change.get("path"), "reason": str(exc)})
      continue
    content = change.get("content")
    if not isinstance(content, str):
      rejected_conflicts.append({"path": path, "reason": "Validated candidate content was unavailable."})
      continue
    if path in seen_changes:
      rejected_conflicts.append({"path": path, "reason": "Multiple dynamic agents proposed the same path."})
      continue
    seen_changes.add(path)
    if path not in merged_by_path:
      ordered_paths.append(path)
    merged_by_path[path] = normalize_generated_file_code(path, content)
    integrated_paths.append(path)
  files = [{"path": path, "content": merged_by_path[path]} for path in ordered_paths]
  return {
    "status": "completed" if not rejected_conflicts else "degraded",
    "files": files,
    "integrated_paths": integrated_paths,
    "rejected_conflicts": rejected_conflicts,
  }


def unique_paths(paths: list[str]) -> list[str]:
  seen: set[str] = set()
  unique: list[str] = []
  for path in paths:
    if path and path not in seen:
      seen.add(path)
      unique.append(path)
  return unique


def tool_files_to_artifact_files(files: list[dict[str, str]], *, changed_file_paths: list[str]) -> list[dict[str, str]]:
  changed = set(changed_file_paths)
  return [
    {
      "path": file_item["path"],
      "purpose": "Updated project file." if file_item["path"] in changed else "Preserved existing project file.",
      "code": file_item["content"],
    }
    for file_item in files
  ]


def project_files_to_tool_files(files: Any) -> list[dict[str, str]]:
  if not isinstance(files, list):
    return []
  restored: list[dict[str, str]] = []
  for file_item in files:
    if not isinstance(file_item, dict):
      continue
    path = file_item.get("path")
    content = file_item.get("content")
    if isinstance(path, str) and isinstance(content, str):
      restored.append({"path": path, "content": content})
  return restored
