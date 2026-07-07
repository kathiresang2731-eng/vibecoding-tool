from __future__ import annotations

from typing import Any

from .values import list_value, object_value, text_value


def build_handoffs(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
  handoffs: list[dict[str, Any]] = []
  for source, target in zip(steps, steps[1:]):
    source_agent = text_value(source.get("agent"), "Source Agent")
    target_agent = text_value(target.get("agent"), "Target Agent")
    source_internal_agent = text_value(source.get("internal_agent"), source_agent)
    target_internal_agent = text_value(target.get("internal_agent"), target_agent)
    source_action = text_value(source.get("action"), "completed_agent_step")
    target_action = text_value(target.get("action"), "run_next_agent_step")
    source_output = object_value(source.get("output"))
    target_input = object_value(target.get("input"))
    requested_tool_calls = list_value(target.get("tool_calls"))
    handoffs.append(
      {
        "from_agent": source_agent,
        "to_agent": target_agent,
        "sender": source_agent,
        "receiver": target_agent,
        "from_internal_agent": source_internal_agent,
        "to_internal_agent": target_internal_agent,
        "status": "completed",
        "task": f"Run {target_action} after {source_action}.",
        "input": target_input,
        "output": source_output,
        "confidence": 0.9 if requested_tool_calls else 0.92,
        "next_action": target_action,
        "requested_tool_calls": requested_tool_calls,
        "completed_action": source_action,
        "message": {
          "action_completed": source_action,
          "next_action": target_action,
          "payload": source_output,
        },
      }
    )
  return handoffs
