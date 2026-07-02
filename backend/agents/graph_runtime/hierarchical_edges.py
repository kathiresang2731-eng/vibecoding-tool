from __future__ import annotations

from typing import Any

from langgraph.graph import END

from .hierarchical_teams import CHIEF_SUPERVISOR, resolve_pending_team


def route_after_chief(state: dict[str, Any]) -> str:
  if state.get("completed"):
    return END
  if int(state.get("_graph_step_count") or 0) >= int(state.get("_graph_max_steps") or 28):
    return END
  team = resolve_pending_team(state)
  if team:
    return team
  return CHIEF_SUPERVISOR


def route_after_team(_state: dict[str, Any]) -> str:
  return CHIEF_SUPERVISOR
