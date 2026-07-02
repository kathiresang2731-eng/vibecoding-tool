from __future__ import annotations

from typing import Any


def redact_project_diff_for_audit(diff_payload: dict[str, Any] | None) -> dict[str, Any]:
  payload = diff_payload or {}
  return {
    "file_count": payload.get("file_count", 0),
    "visible_file_count": payload.get("visible_file_count", 0),
    "truncated_files": payload.get("truncated_files", 0),
    "added": payload.get("added", 0),
    "removed": payload.get("removed", 0),
    "files": [
      {
        "path": item.get("path"),
        "status": item.get("status"),
        "added": item.get("added", 0),
        "removed": item.get("removed", 0),
        "old_hash": item.get("old_hash"),
        "new_hash": item.get("new_hash"),
        "old_size": item.get("old_size", 0),
        "new_size": item.get("new_size", 0),
        "truncated": bool(item.get("truncated")),
      }
      for item in payload.get("diffs", [])
      if isinstance(item, dict)
    ],
  }
