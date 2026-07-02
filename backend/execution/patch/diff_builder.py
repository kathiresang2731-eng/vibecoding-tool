from __future__ import annotations

import difflib
from typing import Any


def build_unified_patches_from_file_changes(
  existing_files: list[dict[str, Any]],
  changed_files: list[dict[str, Any]],
) -> list[dict[str, str]]:
  """Build APPLY_PATCH payloads from before/after file snapshots."""
  existing_map = {
    str(item.get("path") or "").strip(): str(item.get("content") or "")
    for item in existing_files
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  }
  patches: list[dict[str, str]] = []
  for item in changed_files:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    new_content = str(item.get("content") or "")
    old_content = existing_map.get(path, "")
    if old_content == new_content:
      continue
    diff_lines = list(
      difflib.unified_diff(
        old_content.splitlines(),
        new_content.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
      )
    )
    if not diff_lines:
      continue
    patches.append({"path": path, "unified_diff": "\n".join(diff_lines)})
  return patches
