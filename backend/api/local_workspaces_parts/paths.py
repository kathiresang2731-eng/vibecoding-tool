from __future__ import annotations

from pathlib import Path
from typing import Any

try:
  from ...config import Settings
  from ...local_workspace import LocalWorkspaceError, resolve_local_project_path
except ImportError:
  from config import Settings
  from local_workspace import LocalWorkspaceError, resolve_local_project_path

from ..context import AppContext


def resolve_directory_listing_path(settings: Settings, raw_path: str | None) -> Path:
  first_root = settings.local_workspace_roots[0]
  if first_root.exists() and not first_root.is_dir():
    raise LocalWorkspaceError(f"Local workspace root is not a folder: {first_root}")
  first_root.mkdir(parents=True, exist_ok=True)

  if raw_path and raw_path.strip():
    try:
      path = resolve_local_project_path(settings, raw_path)
    except LocalWorkspaceError:
      return first_root
    if path.exists() and not path.is_dir():
      raise LocalWorkspaceError(f"Local path is not a folder: {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path
  return first_root


def serialize_local_directory(path: Path) -> dict[str, str]:
  return {"name": path.name or str(path), "path": str(path.resolve(strict=False))}


def local_parent_path(settings: Settings, current_path: Path) -> str | None:
  parent = current_path.parent.resolve(strict=False)
  if parent == current_path:
    return None
  if not path_is_inside_allowed_root(settings, parent):
    return None
  return str(parent)


def path_is_inside_allowed_root(settings: Settings, path: Path) -> bool:
  resolved_path = path.resolve(strict=False)
  for root in settings.local_workspace_roots:
    resolved_root = root.resolve(strict=False)
    if resolved_path == resolved_root or resolved_root in resolved_path.parents:
      return True
  return False


def should_hide_local_directory(path: Path) -> bool:
  return path.name.startswith(".") or path.name in {"__pycache__", "dist", "node_modules"}


def normalize_local_folder_name(raw_name: str) -> str:
  name = raw_name.strip()
  if not name or "/" in name or "\\" in name or name in {".", ".."}:
    raise LocalWorkspaceError("Folder name must be a single local folder name.")
  if any(part == ".." for part in Path(name).parts):
    raise LocalWorkspaceError("Folder name cannot include traversal.")
  return name


def require_linked_local_root(context: AppContext, project: dict[str, Any]) -> Any:
  local_path = project.get("local_path")
  if not isinstance(local_path, str) or not local_path.strip():
    raise LocalWorkspaceError("Project is not linked to a local folder.")
  return resolve_local_project_path(context.settings, local_path)

