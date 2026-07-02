from __future__ import annotations

from typing import Any


def text_values_from_mapping(value: Any) -> list[str]:
  if not isinstance(value, dict):
    return []
  return [str(item) for item in value.values() if isinstance(item, str)]
