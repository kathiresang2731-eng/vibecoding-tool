from __future__ import annotations

from typing import Any, TypedDict


class RuntimeGraphState(TypedDict, total=False):
  project_id: str
  prompt: str
  routing_result: dict[str, Any]
  operation: str
  read_result: dict[str, Any] | None
  memory_result: dict[str, Any] | None
  brief: dict[str, Any] | None
  plan: dict[str, Any] | None
  generated_website: dict[str, Any] | None
  validation_result: dict[str, Any] | None
  preview_result: dict[str, Any] | None
  visual_qa_result: dict[str, Any] | None
  tool_calls: list[dict[str, Any]]
  agent_steps: list[dict[str, Any]]
  mas_run: dict[str, Any]
  a2a_messages: list[dict[str, Any]]
  action_history: list[str]
  completed: bool
  runtime_engine: str
  agentic_parity_target: int
  _graph_step_count: int
  _pending_action: str
  _pending_decision: dict[str, Any]


def ensure_a2a_bus(state: dict[str, Any]) -> list[dict[str, Any]]:
  messages = state.get("a2a_messages")
  if isinstance(messages, list):
    return messages
  state["a2a_messages"] = []
  return state["a2a_messages"]
