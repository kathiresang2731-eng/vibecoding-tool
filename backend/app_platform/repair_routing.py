from __future__ import annotations

from typing import Any


def failure_repair_route(*, category: str, code: str, raw_error: str = "") -> dict[str, Any]:
  """Map failure categories to supervisor repair behavior (Codex/Cursor skill Example 9)."""
  lowered = str(raw_error or "").lower()
  route = _ROUTE_BY_CATEGORY.get(category)
  if route is not None:
    return dict(route)
  if "path outside allowed" in lowered or "outside the allowed project surface" in lowered:
    return dict(_POLICY_DENIED)
  if "recitation" in lowered or "finishreason" in lowered and "recitation" in lowered:
    return dict(_MODEL_BLOCKED)
  if "dictionary changed size during iteration" in lowered:
    return dict(_RUNTIME_BUG)
  if category == "update_clarification":
    return dict(_NEEDS_USER_INPUT)
  return {
    "action": "surface_error",
    "retry_model": False,
    "retry_tool": False,
    "route_agent": None,
    "reason": code or category or "unknown_failure",
  }


_ROUTE_BY_CATEGORY: dict[str, dict[str, Any]] = {
  "policy_denied": {
    "action": "repair_with_valid_paths",
    "retry_model": False,
    "retry_tool": True,
    "route_agent": "Repair Agent",
    "reason": "Blocked by path or policy validation.",
  },
  "model_blocked": {
    "action": "rephrase_or_switch_model",
    "retry_model": True,
    "retry_tool": False,
    "route_agent": "Supervisor Agent",
    "reason": "Model safety filter blocked generation.",
  },
  "runtime_bug": {
    "action": "fix_runtime_state",
    "retry_model": False,
    "retry_tool": False,
    "route_agent": None,
    "reason": "Runtime state mutation bug; do not retry blindly.",
  },
  "needs_user_input": {
    "action": "return_to_user",
    "retry_model": False,
    "retry_tool": False,
    "route_agent": "Conversation Agent",
    "reason": "Clarification required before editing files.",
  },
  "gate_failure": {
    "action": "route_to_repair",
    "retry_model": True,
    "retry_tool": False,
    "route_agent": "Repair Agent",
    "reason": "Validation gate failed; repair agent should fix artifact issues.",
  },
}

_POLICY_DENIED = _ROUTE_BY_CATEGORY["policy_denied"]
_MODEL_BLOCKED = _ROUTE_BY_CATEGORY["model_blocked"]
_RUNTIME_BUG = _ROUTE_BY_CATEGORY["runtime_bug"]
_NEEDS_USER_INPUT = _ROUTE_BY_CATEGORY["needs_user_input"]
