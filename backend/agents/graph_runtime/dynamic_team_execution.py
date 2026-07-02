from __future__ import annotations

from typing import Any

from ..agent_runtime.loop_core import RuntimeLoopParams, run_action_for_decision, run_supervisor_decision
from ..agent_runtime.supervision import available_runtime_actions
from .a2a.bus import publish_dynamic_agent_spawns, publish_supervisor_handoff
from .dynamic_spawn_runtime import sync_dynamic_spawn_state
from .hierarchical_teams import DYNAMIC_AGENTS_TEAM, TEAM_MAX_BATCH_ACTIONS, team_for_action


def execute_dynamic_team_batch(state: dict[str, Any], params: RuntimeLoopParams) -> dict[str, Any]:
  """Batch planner → spawned specialists → patch integration inside the dynamic agents team."""
  executed = 0
  pending = str(state.get("_pending_action") or "")
  if pending and team_for_action(pending) == DYNAMIC_AGENTS_TEAM:
    state = _run_dynamic_team_action(state, params, pending)
    executed += 1

  while executed < TEAM_MAX_BATCH_ACTIONS and not state.get("completed"):
    available = available_runtime_actions(state, max_repair_attempts=params.repair_attempt_budget)
    if not available:
      break
    if not _available_actions_for_team(available, DYNAMIC_AGENTS_TEAM):
      break

    updated, decision, terminal = run_supervisor_decision(state, params)
    state = updated
    if terminal == "DONE":
      return state

    action = str(decision.get("next_action") or "")
    if team_for_action(action) != DYNAMIC_AGENTS_TEAM:
      publish_supervisor_handoff(state, decision)
      return state

    publish_supervisor_handoff(state, decision)
    state = _run_dynamic_team_action(state, params, action)
    executed += 1

  return state


def _run_dynamic_team_action(state: dict[str, Any], params: RuntimeLoopParams, action: str) -> dict[str, Any]:
  state = run_action_for_decision(state, params, action=action)
  if action == "RUN_DYNAMIC_AGENT_PLANNER":
    state = sync_dynamic_spawn_state(state)
    publish_dynamic_agent_spawns(state, list(state.get("spawned_dynamic_agents") or []))
  if action == "RUN_DYNAMIC_SPECIALISTS":
    state = sync_dynamic_spawn_state(state)
    spawn_graph = state.get("dynamic_spawn_graph")
    if isinstance(spawn_graph, dict):
      spawn_graph["specialists_executed"] = True
      state["dynamic_spawn_graph"] = spawn_graph
  return state


def _available_actions_for_team(available_actions: list[dict[str, Any]], team_id: str) -> list[str]:
  names: list[str] = []
  for item in available_actions:
    if not isinstance(item, dict):
      continue
    action = str(item.get("action") or "")
    if team_for_action(action) == team_id:
      names.append(action)
  return names
