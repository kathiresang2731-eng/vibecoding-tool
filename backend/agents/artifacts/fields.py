from __future__ import annotations

from typing import Any

from .errors import ArtifactValidationError


def required_text(source: dict[str, Any], key: str) -> str:
  value = source.get(key)
  if isinstance(value, str) and value.strip():
    return value.strip()
  raise ArtifactValidationError(f"Generated website missing required text field: {key}")


def optional_text(value: Any) -> str:
  if isinstance(value, str):
    return value.strip()
  return ""
