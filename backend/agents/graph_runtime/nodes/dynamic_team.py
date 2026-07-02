from __future__ import annotations

from typing import Any

from ...agent_runtime.loop_core import RuntimeLoopParams
from ...schema.json_safe import sanitize_graph_node_state
from ..a2a.bus import publish_team_handoff
from ..dynamic_spawn_runtime import dynamic_spawning_needed
from ..dynamic_team_execution import execute_dynamic_team_batch
from ..hierarchical_teams import DYNAMIC_AGENTS_TEAM, team_label
from ..team_execution import execute_team_batch


def build_dynamic_team_node(params: RuntimeLoopParams):
  def dynamic_team_node(state: dict[str, Any]) -> dict[str, Any]:
    state["_active_team"] = DYNAMIC_AGENTS_TEAM
    state["dynamic_spawning_active"] = dynamic_spawning_needed(state)
    publish_team_handoff(
      state,
      team_id=DYNAMIC_AGENTS_TEAM,
      team_label=team_label(DYNAMIC_AGENTS_TEAM),
      spawn_mode=bool(state.get("dynamic_spawning_active")),
    )
    if state.get("dynamic_spawning_active"):
      updated = execute_dynamic_team_batch(state, params)
    else:
      updated = execute_team_batch(state, DYNAMIC_AGENTS_TEAM, params)
    updated.pop("_active_team", None)
    return sanitize_graph_node_state(updated)

  dynamic_team_node.__name__ = DYNAMIC_AGENTS_TEAM
  return dynamic_team_node
