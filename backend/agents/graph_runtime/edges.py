from __future__ import annotations

from typing import Any

from langgraph.graph import END

from ..agent_runtime.actions.dispatcher import ACTION_HANDLERS


def route_after_supervisor(state: dict[str, Any]) -> str:
  if state.get("completed"):
    return END
  if int(state.get("_graph_step_count") or 0) >= int(state.get("_graph_max_steps") or 28):
    return END
  action = str(state.get("_pending_action") or "")
  if not action:
    return "supervisor"
  if action in ACTION_HANDLERS:
    return action
  return "supervisor"


def route_after_action(_state: dict[str, Any]) -> str:
  return "supervisor"
