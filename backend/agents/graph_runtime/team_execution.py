from __future__ import annotations

from typing import Any

from ..agent_runtime.loop_core import RuntimeLoopParams, run_action_for_decision, run_supervisor_decision
from ..agent_runtime.supervision import available_runtime_actions
from .a2a.bus import publish_supervisor_handoff
from .hierarchical_teams import TEAM_MAX_BATCH_ACTIONS, team_for_action


def execute_team_batch(state: dict[str, Any], team_id: str, params: RuntimeLoopParams) -> dict[str, Any]:
  """Run multiple supervisor-selected actions for one team before returning to the chief."""
  executed = 0
  pending = str(state.get("_pending_action") or "")
  if pending and team_for_action(pending) == team_id:
    state = run_action_for_decision(state, params, action=pending)
    executed += 1

  while executed < TEAM_MAX_BATCH_ACTIONS and not state.get("completed"):
    available = available_runtime_actions(state, max_repair_attempts=params.repair_attempt_budget)
    if not available:
      break
    if not _available_actions_for_team(available, team_id):
      break

    updated, decision, terminal = run_supervisor_decision(state, params)
    state = updated
    if terminal == "DONE":
      return state

    action = str(decision.get("next_action") or "")
    if team_for_action(action) != team_id:
      publish_supervisor_handoff(state, decision)
      return state

    publish_supervisor_handoff(state, decision)
    state = run_action_for_decision(state, params, action=action)
    executed += 1

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
