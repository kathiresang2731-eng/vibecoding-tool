from __future__ import annotations

from typing import Any

try:
  from ...local_workspace import write_local_project_files
  from ...storage import UserContext
except ImportError:
  from local_workspace import write_local_project_files
  from storage import UserContext

from ..context import AppContext
from .paths import require_linked_local_root


def write_linked_project_files(
  context: AppContext,
  project: dict[str, Any] | None,
  files: list[dict[str, Any]],
  user: UserContext,
  *,
  event_type: str,
  prune_missing: bool = False,
  allow_prune_missing: bool = False,
) -> dict[str, Any] | None:
  if not project or not project.get("local_path"):
    return None
  local_root = require_linked_local_root(context, project)
  count = write_local_project_files(
    local_root,
    files,
    prune_missing=prune_missing,
    allow_prune_missing=allow_prune_missing,
  )
  mode = "replace_all" if prune_missing else "upsert"
  context.store.add_event(project["id"], user.id, event_type, {"path": str(local_root), "count": count, "mode": mode})
  return {"path": str(local_root), "count": count, "mode": mode}

