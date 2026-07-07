from __future__ import annotations

from typing import Any

from ...a2a.messages import build_a2a_message, build_acknowledgement
from ...agent_runtime.constants import REAL_AGENT_RUNTIME_NAME
from ...a2a.utils import text_value
from ...agent_runtime.values import object_value
from ..state import ensure_a2a_bus


def publish_supervisor_handoff(state: dict[str, Any], decision: dict[str, Any]) -> None:
  action = text_value(decision.get("next_action"), "")
  if not action or action == "DONE":
    return
  target_agent = text_value(decision.get("next_agent"), "Target Agent")
  messages = ensure_a2a_bus(state)
  previous_step = (state.get("agent_steps") or [])[-1] if state.get("agent_steps") else None
  source = previous_step if isinstance(previous_step, dict) else {
    "agent": "Supervisor Agent",
    "action": "supervisor_decision",
    "output": {"reason": decision.get("reason")},
  }
  target = {
    "agent": target_agent,
    "action": action,
    "input": {"reason": decision.get("reason"), "audit_id": decision.get("audit_id")},
    "tool_calls": [],
  }
  branch = "website_update" if state.get("operation") == "update" else "website_generation"
  message = build_a2a_message(
    sequence=len(messages) + 1,
    source=source,
    target=target,
    runtime=REAL_AGENT_RUNTIME_NAME,
    branch=branch,
  )
  messages.append(message)
  inbox = state.setdefault("a2a_inbox", {})
  if isinstance(inbox, dict):
    inbox.setdefault(target_agent, []).append(message)


def publish_action_ack(state: dict[str, Any], *, action: str, agent: str) -> None:
  messages = ensure_a2a_bus(state)
  if not messages:
    return
  latest = messages[-1]
  if text_value(latest.get("to_agent"), "") != agent:
    return
  if text_value(latest.get("intent"), "") != action:
    return
  ack = build_acknowledgement(latest)
  ack["action"] = action
  ack["agent"] = agent
  acks = state.setdefault("a2a_acknowledgements", [])
  if isinstance(acks, list):
    acks.append(ack)


def publish_team_handoff(
  state: dict[str, Any],
  *,
  team_id: str,
  team_label: str,
  spawn_mode: bool = False,
) -> None:
  messages = ensure_a2a_bus(state)
  pending_action = text_value(state.get("_pending_action"), "")
  message = build_a2a_message(
    sequence=len(messages) + 1,
    source={
      "agent": "Chief Supervisor",
      "action": "team_route",
      "output": {
        "team_id": team_id,
        "pending_action": pending_action,
        "spawn_mode": spawn_mode,
      },
    },
    target={
      "agent": team_label,
      "action": pending_action or ("dynamic_spawn_batch" if spawn_mode else "team_batch"),
      "input": {"team_id": team_id, "spawn_mode": spawn_mode},
      "tool_calls": [],
    },
    runtime=REAL_AGENT_RUNTIME_NAME,
    branch="website_update" if state.get("operation") == "update" else "website_generation",
  )
  messages.append(message)
  inbox = state.setdefault("a2a_inbox", {})
  if isinstance(inbox, dict):
    inbox.setdefault(team_label, []).append(message)


def publish_dynamic_agent_spawns(state: dict[str, Any], spawned_agents: list[dict[str, Any]]) -> None:
  if not spawned_agents:
    return
  messages = ensure_a2a_bus(state)
  for agent in spawned_agents:
    if not isinstance(agent, dict):
      continue
    agent_name = text_value(agent.get("name"), text_value(agent.get("agent_id"), "Dynamic Agent"))
    message = build_a2a_message(
      sequence=len(messages) + 1,
      source={
        "agent": "Agent Registry Agent",
        "action": "spawn_dynamic_agent",
        "output": {
          "agent_id": agent.get("agent_id"),
          "capabilities": agent.get("capabilities"),
          "lifecycle": agent.get("lifecycle"),
        },
      },
      target={
        "agent": agent_name,
        "action": "RUN_DYNAMIC_SPECIALISTS",
        "input": {
          "task_id": agent.get("task_id"),
          "assignment_type": agent.get("assignment_type"),
        },
        "tool_calls": [],
      },
      runtime=REAL_AGENT_RUNTIME_NAME,
      branch="website_update" if state.get("operation") == "update" else "website_generation",
    )
    messages.append(message)
    inbox = state.setdefault("a2a_inbox", {})
    if isinstance(inbox, dict):
      inbox.setdefault(agent_name, []).append(message)


def pop_agent_inbox(state: dict[str, Any], agent_name: str) -> dict[str, Any] | None:
  inbox = state.get("a2a_inbox")
  if not isinstance(inbox, dict):
    return None
  queue = inbox.get(agent_name)
  if not isinstance(queue, list) or not queue:
    return None
  message = queue.pop(0)
  return message if isinstance(message, dict) else None
