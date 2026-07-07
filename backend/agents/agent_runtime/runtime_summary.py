from __future__ import annotations

import os
from typing import Any

try:
  from ...audit_logging import current_telemetry_context
except ImportError:
  from audit_logging import current_telemetry_context

from ..agentic_flow import AGENT_ROSTER, AGENTIC_RUNTIME_NAME, build_handoffs
from ..dynamic_agents import AgentRegistry, persist_user_dynamic_agents
from ..mas import build_mas_runtime_summary
from .constants import REAL_AGENT_RUNTIME_NAME
from .file_ops import unique_paths
from .progress import completion_proof, completion_status
from .values import list_value, object_value, text_or_default


def build_runtime_summary(
  state: dict[str, Any],
  generated_website: dict[str, Any],
  validation_result: dict[str, Any] | None,
  preview_result: dict[str, Any] | None,
) -> dict[str, Any]:
  steps = state["agent_steps"]
  preview = preview_result.get("version") if isinstance(preview_result, dict) else None
  telemetry = current_telemetry_context()
  is_update = state.get("operation") == "update"
  changed_file_paths = list(state.get("changed_file_paths") or [])
  final_message = (
    f"No code changes were applied for {generated_website['title']}."
    if is_update and not changed_file_paths
    else f"Updated and built {generated_website['title']}."
    if is_update
    else f"Generated and built {generated_website['title']}."
  )
  return {
    "runtime": REAL_AGENT_RUNTIME_NAME,
    "legacy_runtime": AGENTIC_RUNTIME_NAME,
    "status": "completed",
    "request_id": telemetry.request_id if telemetry else None,
    "branch": "website_update" if state.get("operation") == "update" else "website_generation",
    "operation": state.get("operation"),
    "tool_source_of_truth": True,
    "runtime_engine": state.get("runtime_engine"),
    "graph_engine": state.get("runtime_engine") if state.get("runtime_engine") == "langgraph" else None,
    "graph_runtime": _graph_runtime_metadata(state),
    "graph_topology": state.get("graph_topology") or state.get("runtime_graph_topology"),
    "runtime_graph_topology": state.get("runtime_graph_topology") or state.get("graph_topology"),
    "spawned_dynamic_agents": list(state.get("spawned_dynamic_agents") or []),
    "dynamic_spawn_graph": state.get("dynamic_spawn_graph") or {},
    "agentic_parity_target": state.get("agentic_parity_target"),
    "execution_mode": runtime_execution_mode(state),
    "model_runtime": "gemini-native-control-artifact",
    "native_tool_calling": {
      "status": "available",
      "mode": os.getenv("GEMINI_TOOL_CALLING_MODE", "VALIDATED").strip().upper() or "VALIDATED",
      "safety_boundary": "Python executes and validates backend tools before commit.",
    },
    "goal_driven": True,
    "action_history": state.get("action_history", []),
    "completion_status": completion_status(state),
    "completion_proof": {
      "satisfied": completion_proof(state),
      "requirements": completion_status(state),
      "rejections": list(state.get("supervisor_completion_rejections") or []),
    },
    "repair_attempts": state.get("repair_attempts", 0),
    "deterministic_repair_events": state.get("deterministic_repair_events", []),
    "mas_runtime": build_mas_runtime_summary(state),
    "agents": runtime_agent_roster(state),
    "dynamic_agent_workflow": state.get("dynamic_workflow_plan") or {},
    "dynamic_specialist_results": public_dynamic_specialist_results(state.get("dynamic_specialist_results")),
    "dynamic_agent_registry": state.get("dynamic_agent_registry") or {},
    "dynamic_agent_executions": state.get("dynamic_agent_executions") or [],
    "candidate_change_summary": state.get("candidate_change_summary") or {},
    "requirement_trace": state.get("conversation_requirement") or {},
    "token_budget_used": state.get("token_budget_used") or {},
    "code_diff_summary": state.get("code_diff_summary") or {},
    "dynamic_agent_lifecycle_decisions": state.get("dynamic_agent_lifecycle_decisions") or [],
    "steps": steps,
    "targeted_update": state.get("targeted_update") or {},
    "targeted_update_no_match": state.get("targeted_update_no_match") or {},
    "update_analysis": state.get("update_analysis") or {},
    "scoped_update": state.get("scoped_update") or {},
    "scoped_update_task_results": state.get("scoped_update_task_results") or [],
    "handoffs": build_handoffs(steps),
    "tool_calls": state["tool_calls"],
    "messages": state["messages"],
    "a2a_messages": list(state.get("a2a_messages") or []),
    "a2a_acknowledgements": list(state.get("a2a_acknowledgements") or []),
    "supervisor_decisions": state.get("supervisor_decisions", []),
    "supervisor_audit_trail": state.get("supervisor_audit_trail", []),
    "supervisor_policy_fallbacks": state.get("supervisor_policy_fallbacks", []),
    "supervisor_completion_rejections": state.get("supervisor_completion_rejections", []),
    "validation": validation_result or {},
    "preview": preview or {},
    "visual_qa": state.get("visual_qa_result") or {},
    "artifact_fallback": state.get("artifact_fallback"),
    "local_sync": state.get("local_sync"),
    "local_sync_error": state.get("local_sync_error"),
    "loaded_memory": state.get("loaded_memory", []),
    "memory": state.get("memory") or {},
    "unified_memory_context": state.get("unified_memory_context") or "",
    "persisted_memory_events": state.get("persisted_memory_events", []),
    "final_output": {
      "intent": object_value(state.get("routing_result")).get("intent") or "website_generation",
      "message": final_message,
      "file_count": len(generated_website["files"]),
      "changed_file_paths": changed_file_paths,
      "completion_proof_satisfied": completion_proof(state),
      "preview_status": preview.get("status") if isinstance(preview, dict) else None,
      "preview_url": preview.get("preview_url") if isinstance(preview, dict) else None,
      "visual_qa_status": object_value(state.get("visual_qa_result")).get("status"),
    },
  }


def _graph_runtime_metadata(state: dict[str, Any]) -> dict[str, Any] | None:
  if state.get("runtime_engine") != "langgraph":
    return None
  topology = state.get("runtime_graph_topology") or state.get("graph_topology")
  metadata: dict[str, Any] = {
    "engine": "langgraph",
    "graph": "HierarchicalRuntimeGraph" if isinstance(topology, dict) and topology.get("topology") == "hierarchical" else "WebsiteRuntimeGraph",
    "entrypoint": topology.get("chief_supervisor", "supervisor") if isinstance(topology, dict) else "supervisor",
    "action_node_count": len(state.get("action_history") or []),
  }
  if isinstance(topology, dict):
    metadata["topology"] = topology
    metadata["graph_topology"] = topology
  spawned = state.get("spawned_dynamic_agents")
  if spawned:
    metadata["spawned_dynamic_agents"] = spawned
  spawn_graph = state.get("dynamic_spawn_graph")
  if spawn_graph:
    metadata["dynamic_spawn_graph"] = spawn_graph
  return metadata


def runtime_dynamic_agent_registry(state: dict[str, Any], *, user: Any, runtime_objects: dict[str, Any] | None = None) -> AgentRegistry:
  runtime_objects = runtime_objects if isinstance(runtime_objects, dict) else None
  registry = runtime_objects.get("dynamic_agent_registry") if runtime_objects is not None else None
  if isinstance(registry, AgentRegistry):
    return registry
  registry = AgentRegistry(owner_user_id=text_or_default(getattr(user, "id", None), "") or None)
  if runtime_objects is not None:
    runtime_objects["dynamic_agent_registry"] = registry
  return registry


def promote_dynamic_agents(
  state: dict[str, Any],
  *,
  tool_context: ToolRuntimeContext | None = None,
  user: Any = None,
  runtime_objects: dict[str, Any] | None = None,
) -> None:
  if state.get("dynamic_agents_promoted"):
    return
  workflow_plan = object_value(state.get("dynamic_workflow_plan"))
  assignments = list_value(workflow_plan.get("assignments"))
  registry = runtime_dynamic_agent_registry(state, user=user, runtime_objects=runtime_objects)
  failed_agent_ids: set[str] = set()
  for decision in list_value(state.get("dynamic_agent_lifecycle_decisions")):
    if isinstance(decision, dict) and decision.get("type") in {"contribution_failed", "safety_violation", "execution_failure"}:
      failed_agent_ids.update(text_or_default(agent_id, "") for agent_id in list_value(decision.get("agent_ids")))
  successful_assignments = [
    assignment
    for assignment in assignments
    if not isinstance(assignment, dict) or text_or_default(assignment.get("agent_id"), "") not in failed_agent_ids
  ]
  registry.mark_workflow_success(successful_assignments)
  active_agent_ids = [
    text_or_default(item.get("agent_id"), "")
    for item in assignments
    if isinstance(item, dict)
  ]
  state["dynamic_agent_registry"] = registry.snapshot(agent_ids=active_agent_ids)
  state["dynamic_agent_lifecycle_decisions"].append(
    {
      "type": "workflow_success",
      "agent_ids": active_agent_ids,
      "registry": state["dynamic_agent_registry"],
    }
  )
  if tool_context is not None and user is not None:
    persist_user_dynamic_agents(getattr(tool_context, "store", None), user, registry, agent_ids=active_agent_ids)
  state["dynamic_agents_promoted"] = True


def record_dynamic_contribution_failure(
  state: dict[str, Any],
  *,
  reason: str,
  tool_context: ToolRuntimeContext | None,
  user: Any,
  runtime_objects: dict[str, Any] | None = None,
) -> None:
  if state.get("dynamic_agent_failure_recorded"):
    return
  contributing_agent_ids = unique_paths(
    [
      text_or_default(change.get("agent_id"), "")
      for change in list_value(state.get("candidate_changes"))
      if isinstance(change, dict)
    ]
  )
  if not contributing_agent_ids:
    return
  assignments = [
    assignment
    for assignment in list_value(object_value(state.get("dynamic_workflow_plan")).get("assignments"))
    if isinstance(assignment, dict) and text_or_default(assignment.get("agent_id"), "") in contributing_agent_ids
  ]
  registry = runtime_dynamic_agent_registry(state, user=user, runtime_objects=runtime_objects)
  registry.mark_workflow_failure(assignments, reason=reason)
  state["dynamic_agent_failure_recorded"] = True
  state["dynamic_agent_lifecycle_decisions"].append(
    {"type": "contribution_failed", "agent_ids": contributing_agent_ids, "reason": reason[:1200]}
  )
  state["dynamic_agent_registry"] = registry.snapshot(agent_ids=contributing_agent_ids)
  if tool_context is not None and user is not None:
    persist_user_dynamic_agents(getattr(tool_context, "store", None), user, registry, agent_ids=contributing_agent_ids)


def public_dynamic_specialist_results(value: Any) -> dict[str, Any]:
  results = object_value(value)
  public_results: dict[str, Any] = {}
  for task_id, raw_result in list(object_value(results.get("results")).items()):
    if not isinstance(raw_result, dict):
      continue
    public_results[task_id] = {
      key: compact_public_dynamic_tool_calls(item) if key == "tool_calls" else item
      for key, item in raw_result.items()
      if key not in {"accepted_candidate_changes", "rejected_candidate_changes"}
    }
  return {
    key: item
    for key, item in list(results.items())
    if key not in {"results", "candidate_changes"}
  } | {"results": public_results}


def compact_public_dynamic_tool_calls(value: Any) -> list[dict[str, Any]]:
  return [
    {
      "call_id": item.get("call_id"),
      "name": item.get("name"),
      "status": item.get("status"),
      "error": item.get("error"),
    }
    for item in list_value(value)
    if isinstance(item, dict)
  ]


def runtime_agent_roster(state: dict[str, Any]) -> list[dict[str, Any]]:
  if state.get("operation") == "update" and (state.get("targeted_update") or state.get("scoped_update")):
    definitions = {
      text_or_default(agent.get("name"), ""): dict(agent)
      for agent in AGENT_ROSTER
      if isinstance(agent, dict) and text_or_default(agent.get("name"), "")
    }
    executed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in list_value(state.get("agent_steps")):
      if not isinstance(step, dict):
        continue
      name = text_or_default(step.get("agent"), "")
      if not name or name in seen:
        continue
      definition = definitions.get(name, {})
      executed.append(
        {
          "name": name,
          "mode": "executed",
          "responsibility": text_or_default(definition.get("responsibility"), "Executed an approved update-runtime step."),
        }
      )
      seen.add(name)
    return executed
  roster = [dict(agent) for agent in AGENT_ROSTER]
  existing_names = {text_or_default(agent.get("name"), "") for agent in roster}
  workflow = object_value(state.get("dynamic_workflow_plan"))
  for agent in list_value(workflow.get("active_agents")):
    if not isinstance(agent, dict):
      continue
    name = text_or_default(agent.get("name"), "")
    if not name or name in existing_names:
      continue
    roster.append(
      {
        "name": name,
        "mode": "dynamic",
        "responsibility": text_or_default(agent.get("role"), "Execute assigned dynamic capability tasks."),
        "capabilities": list_value(agent.get("capabilities")),
        "lifecycle": agent.get("lifecycle"),
        "assigned_tasks": list_value(agent.get("assigned_tasks")),
      }
    )
    existing_names.add(name)
  return roster


def runtime_execution_mode(state: dict[str, Any]) -> str:
  if state.get("targeted_update"):
    return "model_selected_targeted_patch_loop"
  if state.get("scoped_update"):
    return "model_selected_scoped_update_loop"
  return "dynamic_supervisor_loop"
