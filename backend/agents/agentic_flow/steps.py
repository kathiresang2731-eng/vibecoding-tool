from __future__ import annotations

from typing import Any

from backend.agents.canonical_roles import canonical_role_for_agent


def agent_step(
  *,
  index: int,
  agent: str,
  action: str,
  input_payload: dict[str, Any],
  output_payload: dict[str, Any],
  tool_calls: list[str] | None = None,
) -> dict[str, Any]:
  canonical_role = canonical_role_for_agent(agent)
  return {
    "index": index,
    "agent": canonical_role,
    "canonical_role": canonical_role,
    "internal_agent": agent,
    "action": action,
    "status": "completed",
    "input": input_payload,
    "output": output_payload,
    "tool_calls": tool_calls or [],
  }
