from __future__ import annotations

from typing import Any, Callable

from ..agent_runtime.actions.dispatcher import ACTION_HANDLERS
from ..agent_runtime.loop_core import RuntimeLoopParams, run_action_for_decision
from ..agent_runtime.supervision import ACTION_REGISTRY
from ..schema.json_safe import sanitize_graph_node_state
from .a2a.bus import pop_agent_inbox, publish_action_ack


def make_action_node(action: str, params: RuntimeLoopParams) -> Callable[[dict[str, Any]], dict[str, Any]]:
  registry = ACTION_REGISTRY.get(action, {})
  agent_name = str(registry.get("agent") or "Agent")

  def action_node(state: dict[str, Any]) -> dict[str, Any]:
    pop_agent_inbox(state, agent_name)
    updated = run_action_for_decision(state, params, action=action)
    publish_action_ack(updated, action=action, agent=agent_name)
    return sanitize_graph_node_state(updated)

  action_node.__name__ = f"action_{action.lower()}"
  return action_node


def action_node_names() -> list[str]:
  return list(ACTION_HANDLERS.keys())
