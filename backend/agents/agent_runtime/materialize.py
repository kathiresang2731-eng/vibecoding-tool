from __future__ import annotations

import hashlib
from typing import Any, Callable

try:
  from ...local_workspace import resolve_local_project_path, write_local_project_files
except ImportError:
  from local_workspace import resolve_local_project_path, write_local_project_files

from .progress import emit_runtime_progress
from .tooling import execute_tool_call
from .values import list_value, object_value, string_list, text_or_default

try:
  from ..patch_approval import require_patch_approval_before_commit
except ImportError:
  from patch_approval import require_patch_approval_before_commit

try:
  from ..project_workspace import is_standalone_code_project, is_standalone_code_source_path
except ImportError:
  from agents.project_workspace import is_standalone_code_project, is_standalone_code_source_path

ToolExecutor = Callable[..., dict[str, Any]]

_FILE_WRITE_PRIORITY = (
  "index.html",
  "package.json",
  "vite.config.js",
  "vite.config.ts",
  "tailwind.config.js",
  "postcss.config.js",
  "src/main.jsx",
  "src/main.tsx",
  "src/App.jsx",
  "src/App.tsx",
  "src/index.css",
)


def file_materialization_sort_key(file_item: dict[str, Any]) -> tuple[int, int, str]:
  path = text_or_default(file_item.get("path"), "")
  for index, prefix in enumerate(_FILE_WRITE_PRIORITY):
    if path == prefix or path.startswith(prefix):
      return (0, index, path)
  return (1, 0, path)


def _file_content_value(file_item: dict[str, Any]) -> str:
  content = file_item.get("content")
  if content is None:
    content = file_item.get("code")
  return content if isinstance(content, str) else ""


def _file_content_signature(path: str, content: str) -> str:
  digest = hashlib.sha256(f"{path}\n{content}".encode("utf-8")).hexdigest()
  return digest[:24]


def pending_materialization_files(state: dict[str, Any]) -> list[dict[str, str]]:
  signatures = object_value(state.get("materialized_file_signatures"))
  pending: list[dict[str, str]] = []
  for file_item in list_value(state.get("candidate_files")):
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    if not path:
      continue
    content = _file_content_value(file_item)
    if signatures.get(path) == _file_content_signature(path, content):
      continue
    pending.append({"path": path, "content": content})
  pending.sort(key=file_materialization_sort_key)
  return pending


def all_candidate_files(state: dict[str, Any]) -> list[dict[str, str]]:
  files: list[dict[str, str]] = []
  for file_item in list_value(state.get("candidate_files")):
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    if not path:
      continue
    files.append({"path": path, "content": _file_content_value(file_item)})
  files.sort(key=file_materialization_sort_key)
  return files


def _filter_standalone_update_candidates(
  state: dict[str, Any],
  *,
  tool_context: Any,
  user: Any,
  project_id: str,
  progress: Callable[..., None],
) -> None:
  if str(state.get("operation") or "") != "update":
    return
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "list_files"):
    return
  try:
    existing_files = store.list_files(project_id, user)
  except Exception:
    return
  if not is_standalone_code_project(existing_files):
    return
  candidate_files = all_candidate_files(state)
  filtered = [item for item in candidate_files if is_standalone_code_source_path(item["path"])]
  removed_paths = [item["path"] for item in candidate_files if item not in filtered]
  if not removed_paths:
    return
  state["candidate_files"] = filtered
  generated_website = state.get("generated_website")
  if isinstance(generated_website, dict):
    generated_website["files"] = filtered
  emit_runtime_progress(
    progress,
    "files.scaffold_filtered",
    f"Skipped {len(removed_paths)} website scaffold file(s) for standalone code update",
    status="completed",
    detail={"removed_paths": removed_paths, "kept_paths": [item["path"] for item in filtered]},
  )


def materialize_candidate_files_incrementally(
  state: dict[str, Any],
  *,
  tool_executor: ToolExecutor,
  tool_context: Any,
  user: Any,
  project_id: str,
  progress: Callable[..., None],
  agent: str = "Code Agent",
) -> dict[str, Any] | None:
  _filter_standalone_update_candidates(
    state,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
  )
  pending_files = pending_materialization_files(state)
  if not pending_files:
    state["files_materialized"] = bool(all_candidate_files(state))
    state["committed"] = bool(state.get("files_materialized"))
    return state.get("local_sync")

  if require_patch_approval_before_commit(
    state,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
    patch_action=state.get("patch_action"),
  ):
    return state.get("local_sync")

  candidate_files = all_candidate_files(state)
  total_count = len(candidate_files)
  signatures = dict(object_value(state.get("materialized_file_signatures")))
  written_paths = set(string_list(state.get("materialized_file_paths"), []))
  local_sync = object_value(state.get("local_sync"))
  store = getattr(tool_context, "store", None)
  settings = getattr(tool_context, "settings", None)
  project = store.get_project(project_id, user) if store is not None and hasattr(store, "get_project") else None
  local_root = None
  if project and project.get("local_path") and settings is not None:
    try:
      local_root = resolve_local_project_path(settings, str(project["local_path"]))
    except Exception:
      local_root = None

  emit_runtime_progress(
    progress,
    "files.materializing",
    f"Writing {len(pending_files)} planned file(s) to the project workspace",
    status="running",
    detail={"pending_count": len(pending_files), "total_count": total_count},
  )

  for file_item in pending_files:
    path = file_item["path"]
    if store is not None and hasattr(store, "apply_generated_files"):
      store.apply_generated_files(project_id, user, [{"path": path, "code": file_item["content"]}])
    else:
      cumulative = [item for item in candidate_files if item["path"] in written_paths or item["path"] == path]
      execute_tool_call(
        state,
        tool_executor=tool_executor,
        tool_context=tool_context,
        user=user,
        agent=agent,
        name="WRITE_PROJECT_FILES",
        arguments={"project_id": project_id, "files": cumulative},
      )
    if local_root is not None:
      write_local_project_files(local_root, [file_item], prune_missing=False)
      local_sync = {
        "direction": "push",
        "path": str(local_root),
        "count": len(written_paths) + 1,
      }

    written_paths.add(path)
    signatures[path] = _file_content_signature(path, file_item["content"])
    written_count = len(written_paths)
    cumulative_files = [item for item in candidate_files if item["path"] in written_paths]
    emit_runtime_progress(
      progress,
      "file.written",
      f"Wrote {path} ({written_count}/{total_count})",
      status="completed",
      detail={
        "path": path,
        "file": file_item,
        "written_count": written_count,
        "total_count": total_count,
        "files": cumulative_files,
        "candidate_files": [{"path": item["path"]} for item in cumulative_files],
      },
    )

  if local_root is not None and state.get("operation") != "update":
    write_local_project_files(local_root, candidate_files, prune_missing=False)
    local_sync = {"direction": "push", "path": str(local_root), "count": len(candidate_files)}

  state["materialized_file_paths"] = sorted(written_paths)
  state["materialized_file_signatures"] = signatures
  state["files_materialized"] = len(written_paths) >= total_count and total_count > 0
  state["committed"] = bool(state.get("files_materialized"))
  if local_sync:
    state["local_sync"] = local_sync

  emit_runtime_progress(
    progress,
    "files.materialized",
    f"All {total_count} planned file(s) are available in the workspace",
    status="completed",
    detail={
      "file_count": total_count,
      "paths": [item["path"] for item in candidate_files],
      "local_sync": local_sync,
    },
  )
  return local_sync if isinstance(local_sync, dict) else None
