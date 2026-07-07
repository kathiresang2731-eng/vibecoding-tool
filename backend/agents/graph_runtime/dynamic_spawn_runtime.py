from __future__ import annotations

from typing import Any

from ..agent_runtime.supervision import (
  full_dynamic_generation_enabled,
  is_agentic_scoped_update_mode,
  is_scoped_update_dynamic_workflow,
)
from ..agent_runtime.values import list_value, object_value, text_or_default
from .hierarchical_teams import DYNAMIC_AGENTS_TEAM


def dynamic_spawning_needed(state: dict[str, Any]) -> bool:
  """Return True when the run should route through the dynamic agents team."""
  if is_agentic_scoped_update_mode(state):
    return True

  operation = str(state.get("operation") or "")
  workflow = object_value(state.get("dynamic_workflow_plan"))

  if operation == "update":
    return is_scoped_update_dynamic_workflow(workflow) or bool(state.get("update_analysis"))

  if operation != "generate":
    return False

  if not full_dynamic_generation_enabled():
    return False

  if workflow:
    if str(workflow.get("scope") or "") == "direct_generation":
      return False
    return _workflow_has_dynamic_specialists(workflow)

  return True


def _workflow_has_dynamic_specialists(workflow: dict[str, Any]) -> bool:
  for task in list_value(workflow.get("tasks")):
    if isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS":
      return True
  return False


def collect_spawned_agents_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
  workflow = object_value(state.get("dynamic_workflow_plan"))
  if not workflow:
    return []

  registry_snapshot = object_value(state.get("dynamic_agent_registry"))
  registry_agents = object_value(registry_snapshot.get("agents"))
  active_by_id = {
    text_or_default(item.get("id"), ""): item
    for item in list_value(workflow.get("active_agents"))
    if isinstance(item, dict)
  }

  spawned: list[dict[str, Any]] = []
  seen: set[str] = set()

  for agent_id in list_value(workflow.get("created_agent_ids")):
    normalized_id = text_or_default(agent_id, "")
    if not normalized_id or normalized_id in seen:
      continue
    record = _spawn_record_for_agent(
      normalized_id,
      active_by_id.get(normalized_id) or registry_agents.get(normalized_id),
      assignment_type="created",
    )
    if record:
      spawned.append(record)
      seen.add(normalized_id)

  for assignment in list_value(workflow.get("assignments")):
    if not isinstance(assignment, dict):
      continue
    if str(assignment.get("assignment_type") or "") != "created":
      continue
    agent_id = text_or_default(assignment.get("agent_id"), "")
    if not agent_id or agent_id in seen:
      continue
    record = _spawn_record_for_agent(
      agent_id,
      active_by_id.get(agent_id) or registry_agents.get(agent_id),
      assignment_type="created",
      task_id=text_or_default(assignment.get("task_id"), ""),
    )
    if record:
      spawned.append(record)
      seen.add(agent_id)

  return spawned


def _spawn_record_for_agent(
  agent_id: str,
  definition: Any,
  *,
  assignment_type: str,
  task_id: str = "",
) -> dict[str, Any] | None:
  if not agent_id:
    return None
  payload = object_value(definition)
  return {
    "agent_id": agent_id,
    "name": text_or_default(payload.get("name"), agent_id),
    "capabilities": list_value(payload.get("capabilities"))[:6],
    "lifecycle": text_or_default(payload.get("lifecycle"), "experimental"),
    "assignment_type": assignment_type,
    "task_id": task_id,
    "team": DYNAMIC_AGENTS_TEAM,
  }


def build_dynamic_spawn_graph_metadata(state: dict[str, Any], spawned_agents: list[dict[str, Any]]) -> dict[str, Any]:
  workflow = object_value(state.get("dynamic_workflow_plan"))
  parallel_groups = list_value(workflow.get("parallel_groups"))
  specialist_tasks = [
    text_or_default(task.get("id"), "")
    for task in list_value(workflow.get("tasks"))
    if isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS"
  ]

  nodes: list[dict[str, Any]] = [
    {"id": "spawn_planner", "type": "action", "action": "RUN_DYNAMIC_AGENT_PLANNER"},
  ]
  edges: list[dict[str, str]] = []

  previous_node = "spawn_planner"
  for index, agent in enumerate(spawned_agents):
    node_id = f"spawned_{agent['agent_id']}"
    nodes.append(
      {
        "id": node_id,
        "type": "spawned_specialist",
        "agent_id": agent["agent_id"],
        "agent_name": agent["name"],
        "task_id": agent.get("task_id"),
      }
    )
    edges.append({"from": previous_node, "to": node_id, "kind": "spawn"})
    previous_node = node_id

  if specialist_tasks:
    nodes.append({"id": "specialist_fanout", "type": "langgraph_send", "task_ids": specialist_tasks})
    edges.append({"from": previous_node, "to": "specialist_fanout", "kind": "execute"})
    nodes.append({"id": "specialist_reduce", "type": "reduce", "action": "merge_specialist_results"})
    edges.append({"from": "specialist_fanout", "to": "specialist_reduce", "kind": "reduce"})
    previous_node = "specialist_reduce"

  if list_value(state.get("candidate_changes")):
    nodes.append({"id": "patch_integrator", "type": "action", "action": "RUN_DYNAMIC_PATCH_INTEGRATOR"})
    edges.append({"from": previous_node, "to": "patch_integrator", "kind": "integrate"})

  return {
    "team": DYNAMIC_AGENTS_TEAM,
    "spawn_count": len(spawned_agents),
    "nodes": nodes,
    "edges": edges,
    "parallel_groups": parallel_groups,
    "execution_engine": "langgraph_send_for_specialists",
  }


def sync_dynamic_spawn_state(state: dict[str, Any]) -> dict[str, Any]:
  spawned = collect_spawned_agents_from_state(state)
  state["spawned_dynamic_agents"] = spawned
  state["dynamic_spawn_graph"] = build_dynamic_spawn_graph_metadata(state, spawned)
  state["dynamic_spawning_active"] = dynamic_spawning_needed(state)
  return state
