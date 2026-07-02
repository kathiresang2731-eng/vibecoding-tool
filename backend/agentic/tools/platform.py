from __future__ import annotations

import fnmatch
from typing import Any

try:
  from ...agents.artifacts.paths import normalize_artifact_path
  from ...execution.patch import PatchEngineError, apply_patches_to_files
  from ...storage import UserContext
except ImportError:
  from agents.artifacts.paths import normalize_artifact_path
  from execution.patch import PatchEngineError, apply_patches_to_files
  from storage import UserContext

from .definitions import ToolExecutionError, ToolRuntimeContext
from .validators import optional_int, required_string


def search_codebase_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  query = required_string(arguments, "query")
  limit = optional_int(arguments, "limit", fallback=20, minimum=1, maximum=50)
  try:
    from ...context.search import search_project_codebase
  except ImportError:
    from context.search import search_project_codebase
  result = search_project_codebase(_project_files(context, user, project_id), query=query, limit=limit)
  return {"project_id": project_id, **result}


def _project_files(context: ToolRuntimeContext, user: UserContext, project_id: str) -> list[dict[str, Any]]:
  return context.store.list_files(project_id, user)


def read_file_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  path = normalize_artifact_path(required_string(arguments, "path"))
  for item in _project_files(context, user, project_id):
    if isinstance(item, dict) and str(item.get("path") or "") == path:
      content = str(item.get("content") or "")
      return {"project_id": project_id, "path": path, "content": content, "size": len(content)}
  return {"project_id": project_id, "path": path, "content": "", "size": 0, "status": "missing"}


def read_file_range_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  path = normalize_artifact_path(required_string(arguments, "path"))
  start_line = optional_int(arguments, "start_line", fallback=1, minimum=1, maximum=100_000)
  end_line = optional_int(arguments, "end_line", fallback=start_line, minimum=start_line, maximum=100_000)
  payload = read_file_tool(context, user, {"project_id": project_id, "path": path})
  lines = str(payload.get("content") or "").splitlines()
  selected = lines[start_line - 1 : end_line]
  return {
    **payload,
    "start_line": start_line,
    "end_line": end_line,
    "line_count": len(selected),
    "content": "\n".join(selected),
  }


def list_dir_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  prefix = str(arguments.get("path") or "").strip().replace("\\", "/").strip("/")
  entries: list[str] = []
  seen: set[str] = set()
  for item in _project_files(context, user, project_id):
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").replace("\\", "/")
    if prefix:
      normalized_prefix = prefix.strip("/")
      if not (path == normalized_prefix or path.startswith(normalized_prefix + "/")):
        continue
      relative = path[len(normalized_prefix) + 1 :] if path.startswith(normalized_prefix + "/") else ""
      if not relative:
        continue
      child_name = relative.split("/", 1)[0]
      entry = f"{normalized_prefix}/{child_name}"
    else:
      child_name = path.split("/", 1)[0]
      entry = child_name
    if entry and entry not in seen:
      seen.add(entry)
      entries.append(entry)
  return {"project_id": project_id, "path": prefix or ".", "entries": sorted(entries)}


def glob_search_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  pattern = required_string(arguments, "pattern")
  matches: list[str] = []
  for item in _project_files(context, user, project_id):
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "")
    if fnmatch.fnmatch(path, pattern):
      matches.append(path)
  limit = optional_int(arguments, "limit", fallback=50, minimum=1, maximum=200)
  return {"project_id": project_id, "pattern": pattern, "matches": sorted(matches)[:limit], "match_count": len(matches)}


def str_replace_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  path = normalize_artifact_path(required_string(arguments, "path"))
  old_string = arguments.get("old_string")
  new_string = arguments.get("new_string")
  if not isinstance(old_string, str) or not old_string:
    raise ToolExecutionError("old_string must be a non-empty string.")
  if not isinstance(new_string, str):
    raise ToolExecutionError("new_string must be a string.")
  content = ""
  for item in _project_files(context, user, project_id):
    if isinstance(item, dict) and str(item.get("path") or "") == path:
      content = str(item.get("content") or "")
      break
  if not content and old_string:
    raise ToolExecutionError(f"Could not find exact old_string in {path}.")
  occurrences = content.count(old_string)
  if occurrences == 0:
    raise ToolExecutionError(f"Could not find exact old_string in {path}.")
  if occurrences > 1:
    raise ToolExecutionError(
      f"old_string matched {occurrences} times in {path}. Provide a more specific old_string with more surrounding context."
    )
  updated = content.replace(old_string, new_string, 1)
  return {
    "project_id": project_id,
    "path": path,
    "status": "staged",
    "content": updated,
    "size": len(updated),
    "replacements": 1,
    "event_hint": {"type": "patch.proposed", "paths": [path]},
  }


def apply_patch_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  patches = arguments.get("patches")
  if not isinstance(patches, list) or not patches:
    raise ToolExecutionError("patches must be a non-empty array.")
  current_files = _project_files(context, user, project_id)
  try:
    merged_files, summary = apply_patches_to_files(current_files, patches)
  except PatchEngineError as exc:
    raise ToolExecutionError(str(exc)) from exc
  return {
    "project_id": project_id,
    "status": "staged",
    "patch_set": summary,
    "files": merged_files,
    "file_count": len(merged_files),
    "event_hint": {"type": "patch.proposed", "paths": summary["diff_stats"]["paths"]},
  }
