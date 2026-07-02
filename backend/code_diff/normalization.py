from __future__ import annotations

from typing import Any


def normalize_file_map(files: list[dict[str, Any]] | None) -> dict[str, str]:
  normalized: dict[str, str] = {}
  for item in files or []:
    if not isinstance(item, dict):
      continue
    path = item.get("path")
    if not isinstance(path, str) or not path.strip():
      continue
    code = item.get("code")
    if code is None:
      code = item.get("content")
    normalized[path.strip()] = str(code or "")
  return normalized
