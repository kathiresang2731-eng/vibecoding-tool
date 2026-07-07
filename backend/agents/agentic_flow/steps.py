from __future__ import annotations

from typing import Any


def agent_step(
  *,
  index: int,
  agent: str,
  action: str,
  input_payload: dict[str, Any],
  output_payload: dict[str, Any],
  tool_calls: list[str] | None = None,
) -> dict[str, Any]:
  return {
    "index": index,
    "agent": agent,
    "action": action,
    "status": "completed",
    "input": input_payload,
    "output": output_payload,
    "tool_calls": tool_calls or [],
  }
