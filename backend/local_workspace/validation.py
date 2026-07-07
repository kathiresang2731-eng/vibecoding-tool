from __future__ import annotations

from typing import Any

from .constants import REQUIRED_PROJECT_ROOT_FILES, REQUIRED_PROJECT_SOURCE_PREFIX
from .errors import LocalWorkspaceError


def validate_complete_project_import(
  files: list[dict[str, Any]],
  *,
  source_label: str = "Project import",
  require_complete: bool = True,
) -> None:
  if not require_complete or not files:
    return

  paths = {str(file_item.get("path", "")) for file_item in files}
  if "index.html" in paths:
    return

  missing_root_files = sorted(path for path in REQUIRED_PROJECT_ROOT_FILES if path not in paths)
  has_source_file = any(path.startswith(REQUIRED_PROJECT_SOURCE_PREFIX) for path in paths)
  details = []
  if missing_root_files:
    details.append(f"missing {', '.join(missing_root_files)}")
  if not has_source_file:
    details.append("missing src/ source files")
  raise LocalWorkspaceError(
    f"{source_label} is incomplete: {'; '.join(details)}. Choose a static website folder containing index.html, or a Vite/React project root containing index.html, package.json, and src/."
  )
