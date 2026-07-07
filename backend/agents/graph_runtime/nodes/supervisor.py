from __future__ import annotations

from typing import Any

from ...agent_runtime.loop_core import RuntimeLoopParams, run_supervisor_decision
from ...schema.json_safe import sanitize_graph_node_state
from ..a2a.bus import publish_supervisor_handoff


def build_supervisor_node(params: RuntimeLoopParams):
  def supervisor_node(state: dict[str, Any]) -> dict[str, Any]:
    step_count = int(state.get("_graph_step_count") or 0) + 1
    state["_graph_step_count"] = step_count
    updated, decision, terminal = run_supervisor_decision(state, params)
    if terminal != "DONE":
      publish_supervisor_handoff(updated, decision)
    return sanitize_graph_node_state(updated)

  return supervisor_node
