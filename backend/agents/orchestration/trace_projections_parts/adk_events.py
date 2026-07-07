from __future__ import annotations

from typing import Any

from .common import AGENT_TO_ADK_NAME, _list, _obj, _text


def _build_adk_events(*, runtime_trace: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  steps = _list(runtime_trace.get("steps"))
  messages = _list(a2a_runtime.get("messages"))
  incoming_by_agent = {message.get("to_agent"): message for message in messages if isinstance(message, dict)}
  outgoing_by_agent = {message.get("from_agent"): message for message in messages if isinstance(message, dict)}
  events: list[dict[str, Any]] = []
  for step in steps:
    if not isinstance(step, dict):
      continue
    agent_name = _text(step.get("agent"), "Unknown Agent")
    adk_agent_name = AGENT_TO_ADK_NAME.get(agent_name, agent_name.lower().replace(" ", "_"))
    events.append(
      {
        "event_id": f"adk-event-{len(events) + 1}-{adk_agent_name}",
        "author": adk_agent_name,
        "source_agent": agent_name,
        "status": _text(step.get("status"), "completed"),
        "action": _text(step.get("action"), "agent_step"),
        "tool_calls": _list(step.get("tool_calls")),
        "a2a_received_message_id": _obj(incoming_by_agent.get(agent_name)).get("message_id"),
        "a2a_sent_message_id": _obj(outgoing_by_agent.get(agent_name)).get("message_id"),
      }
    )
  return events
