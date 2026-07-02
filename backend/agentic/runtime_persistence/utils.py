from __future__ import annotations

from typing import Any

def generation_intent(generation: dict[str, Any]) -> str:
  return text_value(generation.get("multi_agent_system", {}).get("intent"), "unknown")


def active_agent_name(generation: dict[str, Any]) -> str:
  return text_value(generation.get("multi_agent_system", {}).get("active_agent"), "Worktual AI Dev")


def text_value(value: Any, fallback: str) -> str:
  if isinstance(value, str) and value.strip():
    return value.strip()
  return fallback


def object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {"value": value}
