from __future__ import annotations


def normalize_tool_calling_mode(value: str) -> str:
  mode = value.strip().upper()
  if mode not in {"VALIDATED", "AUTO", "ANY", "NONE"}:
    return "VALIDATED"
  return mode
