from __future__ import annotations

from typing import Any

from ...agent_runtime.loop_core import RuntimeLoopParams
from ...schema.json_safe import sanitize_graph_node_state
from ..a2a.bus import publish_team_handoff
from ..hierarchical_teams import team_label
from ..team_execution import execute_team_batch


def build_team_node(team_id: str, params: RuntimeLoopParams):
  def team_node(state: dict[str, Any]) -> dict[str, Any]:
    state["_active_team"] = team_id
    publish_team_handoff(state, team_id=team_id, team_label=team_label(team_id))
    updated = execute_team_batch(state, team_id, params)
    updated.pop("_active_team", None)
    return sanitize_graph_node_state(updated)

  team_node.__name__ = team_id
  return team_node
