from __future__ import annotations

from typing import Any

from .values import list_value, text_value


def runtime_tool_names(runtime: dict[str, Any]) -> list[str]:
  names: list[str] = []
  for call in list_value(runtime.get("tool_calls")):
    if isinstance(call, dict):
      name = text_value(call.get("name"))
      if name and name not in names:
        names.append(name)
  return names
