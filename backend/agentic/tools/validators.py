from __future__ import annotations

from typing import Any

try:
  from ...agents.artifacts import normalize_artifact_path
except ImportError:
  from agents.artifacts import normalize_artifact_path

from .definitions import ToolExecutionError

def required_string(arguments: dict[str, Any], key: str) -> str:
  value = arguments.get(key)
  if isinstance(value, str) and value.strip():
    return value.strip()
  raise ToolExecutionError(f"Missing required tool argument: {key}")


def optional_string(arguments: dict[str, Any], key: str) -> str | None:
  value = arguments.get(key)
  return value.strip() if isinstance(value, str) and value.strip() else None


def optional_int(arguments: dict[str, Any], key: str, *, fallback: int, minimum: int, maximum: int) -> int:
  value = arguments.get(key)
  if isinstance(value, bool):
    return fallback
  if isinstance(value, int):
    return max(minimum, min(value, maximum))
  return fallback


def required_files(value: Any) -> list[dict[str, str]]:
  if not isinstance(value, list):
    raise ToolExecutionError("files must be a list.")
  if not value:
    return []
  files: list[dict[str, str]] = []
  seen_paths: set[str] = set()
  for index, file_item in enumerate(value, start=1):
    if not isinstance(file_item, dict):
      raise ToolExecutionError(f"files[{index}] must be an object.")
    path = normalize_artifact_path(required_string(file_item, "path"))
    if path in seen_paths:
      raise ToolExecutionError(f"Duplicate file path: {path}")
    content = file_item.get("content")
    if not isinstance(content, str) or not content.strip():
      raise ToolExecutionError(f"files[{index}].content must be non-empty text.")
    seen_paths.add(path)
    files.append({"path": path, "content": content})
  return files
