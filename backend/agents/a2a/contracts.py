from __future__ import annotations

from typing import Any


def build_canonical_handoff_contract(
  *,
  source_agent: str,
  target_agent: str,
  source_action: str,
  target_action: str,
  source_output: dict[str, Any],
  target_input: dict[str, Any],
  requested_tool_calls: list[Any],
) -> dict[str, Any]:
  return {
    "sender": source_agent,
    "receiver": target_agent,
    "task": f"Run {target_action} after {source_action}.",
    "input": target_input,
    "output": source_output,
    "confidence": handoff_confidence(target_action=target_action, requested_tool_calls=requested_tool_calls),
    "next_action": target_action,
    "requested_tool_calls": requested_tool_calls,
    "completed_action": source_action,
  }


def handoff_confidence(*, target_action: str, requested_tool_calls: list[Any]) -> float:
  if target_action in {"repair_project_artifact", "restore_previous_project_files"}:
    return 0.82
  if requested_tool_calls:
    return 0.9
  return 0.92
