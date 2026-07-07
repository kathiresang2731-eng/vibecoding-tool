from __future__ import annotations

from typing import Any

try:
  from ..agents.schema.json_safe import json_dumps_for_persistence
except ImportError:
  from agents.schema.json_safe import json_dumps_for_persistence


def serialize_row(row: Any) -> dict[str, Any]:
  if row is None:
    return {}
  result = dict(row)
  for key, value in list(result.items()):
    if hasattr(value, "isoformat"):
      result[key] = value.isoformat()
  return result


def json_dumps_safe(value: Any, *, context: str = "storage_json") -> str:
  return json_dumps_for_persistence(value, context=context)
