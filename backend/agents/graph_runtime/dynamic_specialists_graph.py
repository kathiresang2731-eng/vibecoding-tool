from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from ..dynamic_agenting.execution import (
  candidate_change_summary,
  compact_dynamic_tool_calls,
  execute_specialist_task,
)
from ..dynamic_agenting.utils import list_value, object_value, text_value
from ..schema.json_safe import sanitize_and_validate_for_checkpoint


class SpecialistGraphState(TypedDict, total=False):
  prompt: str
  brief: dict[str, Any]
  plan: dict[str, Any]
  workflow_plan: dict[str, Any]
  group_task_ids: list[str]
  tasks_by_id: dict[str, dict[str, Any]]
  assignments: dict[str, dict[str, Any]]
  worker_results: Annotated[list[dict[str, Any]], operator.add]
  merged_results: dict[str, Any]
  parallel_execution_engine: str


def _assign_specialist_workers(state: SpecialistGraphState) -> list[Send]:
  sends: list[Send] = []
  for task_id in list_value(state.get("group_task_ids")):
    task_item = object_value(state.get("tasks_by_id")).get(task_id)
    if not isinstance(task_item, dict):
      continue
    sends.append(
      Send(
        "dynamic_specialist_worker",
        {
          "task_id": task_id,
          "task_item": task_item,
          "assignment": object_value(state.get("assignments")).get(task_id) or {},
          "prompt": state.get("prompt"),
          "brief": state.get("brief"),
          "plan": state.get("plan"),
        },
      )
    )
  return sends


def _build_specialist_worker_node(
  *,
  provider: Any,
  registry: Any,
  execute_tool: Any | None,
):
  """Bind live runtime objects outside LangGraph state/checkpoints."""

  def _specialist_worker_node(state: dict[str, Any]) -> dict[str, Any]:
    task_id = text_value(state.get("task_id"))
    result = execute_specialist_task(
      provider,
      object_value(state.get("task_item")),
      object_value(state.get("assignment")),
      prompt=str(state.get("prompt") or ""),
      brief=object_value(state.get("brief")),
      plan=object_value(state.get("plan")),
      registry=registry,
      execute_tool=execute_tool,
    )
    return {"worker_results": [{task_id: result}]}

  return _specialist_worker_node


def _reduce_specialist_results(state: SpecialistGraphState) -> dict[str, Any]:
  merged: dict[str, Any] = {}
  for item in list_value(state.get("worker_results")):
    if isinstance(item, dict):
      merged.update(item)
  return {"merged_results": merged}


def execute_parallel_specialist_group(
  *,
  provider: Any,
  workflow_plan: dict[str, Any],
  group_task_ids: list[str],
  prompt: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  registry: Any,
  execute_tool: Any | None,
) -> dict[str, Any]:
  tasks_by_id = {
    text_value(task.get("id")): task
    for task in list_value(workflow_plan.get("tasks"))
    if isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS"
  }
  assignments = {
    text_value(item.get("task_id")): item
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  }
  graph = StateGraph(SpecialistGraphState)
  graph.add_node(
    "dynamic_specialist_worker",
    _build_specialist_worker_node(provider=provider, registry=registry, execute_tool=execute_tool),
  )
  graph.add_node("dynamic_specialist_reduce", _reduce_specialist_results)
  graph.add_conditional_edges("__start__", _assign_specialist_workers, ["dynamic_specialist_worker"])
  graph.add_edge("dynamic_specialist_worker", "dynamic_specialist_reduce")
  graph.add_edge("dynamic_specialist_reduce", END)
  app = graph.compile()
  initial_state = sanitize_and_validate_for_checkpoint(
    {
      "prompt": prompt,
      "brief": brief,
      "plan": plan,
      "workflow_plan": workflow_plan,
      "group_task_ids": group_task_ids,
      "tasks_by_id": tasks_by_id,
      "assignments": assignments,
      "worker_results": [],
      "parallel_execution_engine": "langgraph_send",
    },
    context="dynamic_specialists.initial_state",
  )
  final_state = app.invoke(initial_state)
  return object_value(final_state.get("merged_results"))


def execute_dynamic_specialists_langgraph(
  provider: Any,
  workflow_plan: dict[str, Any],
  *,
  prompt: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  registry: Any | None = None,
  execute_tool: Any | None = None,
) -> dict[str, Any]:
  from ..dynamic_agents import AgentRegistry

  registry = registry or AgentRegistry()
  tasks_by_id = {
    text_value(task.get("id")): task
    for task in list_value(workflow_plan.get("tasks"))
    if isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS"
  }
  results: dict[str, Any] = {}
  completed: list[str] = []
  parallel_groups = list_value(workflow_plan.get("parallel_groups")) or [list(tasks_by_id)]
  executed_groups: list[list[str]] = []
  for raw_group in parallel_groups:
    group_task_ids = [
      text_value(task_id)
      for task_id in list_value(raw_group)
      if text_value(task_id) in tasks_by_id and text_value(task_id) not in completed
    ]
    if not group_task_ids:
      continue
    group_results = execute_parallel_specialist_group(
      provider=provider,
      workflow_plan=workflow_plan,
      group_task_ids=group_task_ids,
      prompt=prompt,
      brief=brief,
      plan=plan,
      registry=registry,
      execute_tool=execute_tool,
    )
    results.update(group_results)
    completed.extend(group_task_ids)
    executed_groups.append(group_task_ids)
  candidate_changes = [
    change
    for result in results.values()
    if isinstance(result, dict)
    for change in list_value(result.get("accepted_candidate_changes"))
    if isinstance(change, dict)
  ]
  rejected_changes = [
    change
    for result in results.values()
    if isinstance(result, dict)
    for change in list_value(result.get("rejected_candidate_changes"))
    if isinstance(change, dict)
  ]
  from ..dynamic_agenting.config import dynamic_agent_max_patch_files

  max_patch_files = dynamic_agent_max_patch_files()
  if len(candidate_changes) > max_patch_files:
    overflow = candidate_changes[max_patch_files:]
    candidate_changes = candidate_changes[:max_patch_files]
    rejected_changes.extend(
      {
        "path": item.get("path"),
        "agent_id": item.get("agent_id"),
        "task_id": item.get("task_id"),
        "reason": f"Workflow candidate file limit of {max_patch_files} exceeded.",
      }
      for item in overflow
    )
  executions = [
    {
      "task_id": task_id,
      "agent_id": result.get("agent_id"),
      "agent": result.get("agent"),
      "status": result.get("status"),
      "source": result.get("source"),
      "duration_ms": result.get("duration_ms"),
      "tool_calls": compact_dynamic_tool_calls(result.get("tool_calls")),
      "safety_violations": list_value(result.get("safety_violations")),
      "execution_failed": bool(result.get("execution_failed")),
      "fallback_reason": result.get("fallback_reason"),
    }
    for task_id, result in list(results.items())
    if isinstance(result, dict)
  ]
  return {
    "status": "completed",
    "results": results,
    "completed_task_ids": completed,
    "parallel_groups_executed": executed_groups,
    "candidate_changes": candidate_changes,
    "candidate_change_summary": candidate_change_summary(candidate_changes, rejected_changes),
    "dynamic_agent_executions": executions,
    "parallel_execution_engine": "langgraph_send",
  }
