from __future__ import annotations

from pathlib import Path
from typing import Any


def materialize_local_candidate(
  *,
  tool_context: Any,
  user: Any,
  project_id: str,
  files: list[dict[str, Any]],
) -> dict[str, Any] | None:
  """Write a syntax-valid candidate to a linked folder and retain an in-memory rollback snapshot."""
  store = getattr(tool_context, "store", None)
  settings = getattr(tool_context, "settings", None)
  if store is None or settings is None or not hasattr(store, "get_project"):
    return None
  project = store.get_project(project_id, user)
  local_path = str((project or {}).get("local_path") or "").strip()
  if not local_path:
    return None

  try:
    from ...local_workspace import (
      resolve_local_project_path,
      restore_local_project_files,
      snapshot_local_project_files,
      write_local_project_files,
    )
  except ImportError:
    from local_workspace import (
      resolve_local_project_path,
      restore_local_project_files,
      snapshot_local_project_files,
      write_local_project_files,
    )

  root = resolve_local_project_path(settings, local_path)
  snapshot = snapshot_local_project_files(root, include_all=False, files=files)
  count = write_local_project_files(root, files, prune_missing=False)
  return {
    "root": root,
    "snapshot": snapshot,
    "path": str(root),
    "file_count": count,
    "paths": [str(item.get("path") or "") for item in files if item.get("path")],
    "restore": restore_local_project_files,
  }


def restore_local_candidate(candidate: dict[str, Any] | None) -> bool:
  if not candidate:
    return False
  root = candidate.get("root")
  snapshot = candidate.get("snapshot")
  restore = candidate.get("restore")
  if not isinstance(root, Path) or not isinstance(snapshot, dict) or not callable(restore):
    return False
  restore(root, snapshot)
  return True
