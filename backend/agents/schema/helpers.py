from __future__ import annotations

from typing import Any


def get_nested_value(source: dict[str, Any], path: tuple[str, ...]) -> Any:
  current = source
  for key in path:
    if not isinstance(current, dict) or key not in current:
      return None
    current = current[key]
  return current
