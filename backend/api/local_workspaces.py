from __future__ import annotations

from pathlib import Path
from typing import Any

try:
  from ..config import Settings
  from ..local_workspace import LocalWorkspaceError
except ImportError:
  from config import Settings
  from local_workspace import LocalWorkspaceError

from .context import AppContext
from .local_workspaces_parts.paths import (
  local_parent_path,
  normalize_local_folder_name,
  path_is_inside_allowed_root,
  require_linked_local_root,
  resolve_directory_listing_path,
  serialize_local_directory,
  should_hide_local_directory,
)
from .local_workspaces_parts.sync import write_linked_project_files

__all__ = [
  "LocalWorkspaceError",
  "AppContext",
  "Path",
  "Any",
  "local_parent_path",
  "normalize_local_folder_name",
  "path_is_inside_allowed_root",
  "require_linked_local_root",
  "resolve_directory_listing_path",
  "serialize_local_directory",
  "should_hide_local_directory",
  "write_linked_project_files",
  "directory_listing_payload",
]


def directory_listing_payload(settings: Settings, current_path: Path) -> dict[str, Any]:
  current_path = current_path.resolve(strict=False)
  directories: list[dict[str, Any]] = []
  for child in sorted(current_path.iterdir(), key=lambda item: item.name.lower()):
    if not child.is_dir() or should_hide_local_directory(child):
      continue
    directories.append(serialize_local_directory(child))
  return {
    "current_path": str(current_path),
    "parent_path": local_parent_path(settings, current_path),
    "roots": [serialize_local_directory(root) for root in settings.local_workspace_roots],
    "directories": directories,
  }

