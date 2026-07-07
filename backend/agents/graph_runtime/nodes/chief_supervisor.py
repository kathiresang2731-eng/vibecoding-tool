from __future__ import annotations

from typing import Any

from ...agent_runtime.loop_core import RuntimeLoopParams, run_supervisor_decision
from ...schema.json_safe import sanitize_graph_node_state
from ..a2a.bus import publish_supervisor_handoff
from ..hierarchical_teams import resolve_pending_team, team_for_action


def build_chief_supervisor_node(params: RuntimeLoopParams):
  def chief_supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    step_count = int(state.get("_graph_step_count") or 0) + 1
    state["_graph_step_count"] = step_count

    pending = str(state.get("_pending_action") or "")
    if pending and team_for_action(pending):
      state["_pending_team"] = resolve_pending_team(state)
      return sanitize_graph_node_state(state)

    updated, decision, terminal = run_supervisor_decision(state, params)
    if terminal != "DONE":
      publish_supervisor_handoff(updated, decision)
      action = str(decision.get("next_action") or "")
      updated["_pending_team"] = team_for_action(action)
    return sanitize_graph_node_state(updated)

  return chief_supervisor_node
