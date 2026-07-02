from __future__ import annotations

try:
  from ....audit_logging import log_dynamic_agent_event
except ImportError:
  from audit_logging import log_dynamic_agent_event

from ...runtime_config import runtime_engine
from ...dynamic_agents import ALLOWED_DYNAMIC_TOOLS, create_dynamic_workflow, persist_user_dynamic_agents
from ...dynamic_agenting.execution import execute_dynamic_specialists
from ..compaction import compact_dynamic_specialist_results_for_prompt
from ..errors import AgentRuntimeLoopError
from ..file_ops import integrate_dynamic_candidate_changes, unique_paths
from ..memory import persist_memory_checkpoint
from ..progress import emit_candidate_code_diff_progress, emit_runtime_progress, sync_generated_website_files_from_candidates, workflow_progress_detail
from ..runtime_summary import runtime_dynamic_agent_registry
from ..state import append_step
from ..supervision import (
  build_scoped_update_dynamic_specialist_results,
  build_scoped_update_dynamic_workflow,
  is_agentic_scoped_update_mode,
  is_scoped_update_dynamic_workflow,
)
from ..values import list_value, object_value, text_or_default
from .context import RuntimeActionContext


def handle_dynamic_agent_planner(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  registry = runtime_dynamic_agent_registry(state, user=user, runtime_objects=ctx.runtime_objects)
  if is_agentic_scoped_update_mode(state):
    workflow_plan = build_scoped_update_dynamic_workflow(
      object_value(state.get("update_analysis")),
      registry=registry,
    )
    state["dynamic_workflow_plan"] = workflow_plan
    state["dynamic_specialists_completed"] = False
    active_agent_ids = [
      text_or_default(item.get("agent_id"), "")
      for item in list_value(workflow_plan.get("assignments"))
      if isinstance(item, dict)
    ]
    state["dynamic_agent_registry"] = registry.snapshot(agent_ids=active_agent_ids)
    prepared_sections["dynamic_agent_workflow"] = workflow_plan
    append_step(
      state,
      agent,
      "create_scoped_dynamic_agent_workflow",
      {
        "domain": workflow_plan.get("domain"),
        "scope": workflow_plan.get("scope"),
        "planning_source": workflow_plan.get("planning_source"),
      },
      {
        "task_count": len(list_value(workflow_plan.get("tasks"))),
        "active_agent_count": len(list_value(workflow_plan.get("active_agents"))),
        "created_agent_ids": list_value(workflow_plan.get("created_agent_ids")),
        "reused_agent_ids": list_value(workflow_plan.get("reused_agent_ids")),
        "parallel_groups": list_value(workflow_plan.get("parallel_groups")),
      },
    )
    emit_runtime_progress(
      progress,
      "plan.created",
      "Scoped dynamic agent workflow plan is ready",
      status="completed",
      detail=workflow_progress_detail(workflow_plan),
    )
    persist_memory_checkpoint(
      state,
      tool_context=tool_context,
      user=user,
      namespace="agent",
      key="latest_dynamic_workflow",
      kind="workflow_plan",
      content=workflow_plan,
      project_id=project_id,
    )
    return

  workflow_plan = create_dynamic_workflow(
    state["prompt"],
    routing_result=object_value(state.get("routing_result")),
    brief=object_value(state.get("brief")),
    provider=control_provider,
    registry=registry,
  )
  state["dynamic_workflow_plan"] = workflow_plan
  state["dynamic_specialists_completed"] = not any(
    isinstance(task, dict) and task.get("runtime_action") == "RUN_DYNAMIC_SPECIALISTS"
    for task in list_value(workflow_plan.get("tasks"))
  )
  active_agent_ids = [
    text_or_default(item.get("agent_id"), "")
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  ]
  state["dynamic_agent_registry"] = registry.snapshot(agent_ids=active_agent_ids)
  persist_user_dynamic_agents(
    getattr(tool_context, "store", None),
    user,
    registry,
    agent_ids=list_value(workflow_plan.get("created_agent_ids")),
  )
  prepared_sections["dynamic_agent_workflow"] = workflow_plan
  append_step(
    state,
    agent,
    "create_dynamic_agent_workflow",
    {
      "domain": workflow_plan.get("domain"),
      "scope": workflow_plan.get("scope"),
    },
    {
      "task_count": len(list_value(workflow_plan.get("tasks"))),
      "active_agent_count": len(list_value(workflow_plan.get("active_agents"))),
      "created_agent_ids": list_value(workflow_plan.get("created_agent_ids")),
      "reused_agent_ids": list_value(workflow_plan.get("reused_agent_ids")),
      "parallel_groups": list_value(workflow_plan.get("parallel_groups")),
    },
  )
  emit_runtime_progress(
    progress,
    "plan.created",
    "Dynamic agent workflow plan is ready",
    status="completed",
    detail=workflow_progress_detail(workflow_plan),
  )
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_dynamic_workflow",
    kind="workflow_plan",
    content=workflow_plan,
    project_id=project_id,
  )
  return

def handle_dynamic_specialists(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  registry = runtime_dynamic_agent_registry(state, user=user, runtime_objects=ctx.runtime_objects)
  if is_scoped_update_dynamic_workflow(state.get("dynamic_workflow_plan")):
    specialist_results = build_scoped_update_dynamic_specialist_results(
      object_value(state.get("dynamic_workflow_plan")),
      object_value(state.get("update_analysis")),
    )
    state["dynamic_specialist_results"] = specialist_results
    state["dynamic_specialists_completed"] = True
    state["dynamic_agent_executions"] = list_value(specialist_results.get("dynamic_agent_executions"))
    state["candidate_changes"] = []
    state["candidate_change_summary"] = object_value(specialist_results.get("candidate_change_summary"))
    prepared_sections["dynamic_specialist_results"] = compact_dynamic_specialist_results_for_prompt(specialist_results)
    append_step(
      state,
      agent,
      "execute_scoped_dynamic_specialists",
      {
        "workflow_domain": object_value(state.get("dynamic_workflow_plan")).get("domain"),
        "assigned_task_count": len(list_value(object_value(state.get("dynamic_workflow_plan")).get("tasks"))),
        "source": specialist_results.get("source"),
      },
      {
        "status": specialist_results.get("status"),
        "completed_task_ids": list_value(specialist_results.get("completed_task_ids")),
        "result_count": len(object_value(specialist_results.get("results"))),
      },
    )
    assignments = list_value(object_value(state.get("dynamic_workflow_plan")).get("assignments"))
    active_agent_ids = [
      text_or_default(item.get("agent_id"), "")
      for item in assignments
      if isinstance(item, dict)
    ]
    state["dynamic_agent_registry"] = registry.snapshot(agent_ids=active_agent_ids)
    persist_user_dynamic_agents(
      getattr(tool_context, "store", None),
      user,
      registry,
      agent_ids=active_agent_ids,
    )
    persist_memory_checkpoint(
      state,
      tool_context=tool_context,
      user=user,
      namespace="agent",
      key="latest_dynamic_specialists",
      kind="specialist_results",
      content=specialist_results,
      project_id=project_id,
    )
    return

  def execute_bound_dynamic_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in ALLOWED_DYNAMIC_TOOLS:
      raise AgentRuntimeLoopError(f"Dynamic agent requested forbidden or unknown tool {name}.")
    model_arguments = object_value(arguments)
    bound_arguments: dict[str, Any] = {"project_id": project_id}
    if name == "LOAD_PROJECT_MEMORY":
      if isinstance(model_arguments.get("namespace"), str):
        bound_arguments["namespace"] = model_arguments["namespace"][:100]
      if isinstance(model_arguments.get("limit"), int):
        bound_arguments["limit"] = max(1, min(model_arguments["limit"], 50))
    return tool_executor(name, tool_context, user, bound_arguments)

  if runtime_engine() == "langgraph":
    from ...graph_runtime.dynamic_specialists_graph import execute_dynamic_specialists_langgraph

    specialist_results = execute_dynamic_specialists_langgraph(
      control_provider,
      object_value(state.get("dynamic_workflow_plan")),
      prompt=state["prompt"],
      brief=object_value(state.get("brief")),
      plan=object_value(state.get("plan")),
      registry=registry,
      execute_tool=execute_bound_dynamic_tool,
    )
  else:
    specialist_results = execute_dynamic_specialists(
      control_provider,
      object_value(state.get("dynamic_workflow_plan")),
      prompt=state["prompt"],
      brief=object_value(state.get("brief")),
      plan=object_value(state.get("plan")),
      registry=registry,
      execute_tool=execute_bound_dynamic_tool,
    )
  state["dynamic_specialist_results"] = specialist_results
  state["dynamic_specialists_completed"] = True
  state["dynamic_agent_executions"] = list_value(specialist_results.get("dynamic_agent_executions"))
  state["candidate_changes"] = list_value(specialist_results.get("candidate_changes"))
  state["candidate_change_summary"] = object_value(specialist_results.get("candidate_change_summary"))
  prepared_sections["dynamic_specialist_results"] = compact_dynamic_specialist_results_for_prompt(specialist_results)
  append_step(
    state,
    agent,
    "execute_dynamic_specialists",
    {
      "workflow_domain": object_value(state.get("dynamic_workflow_plan")).get("domain"),
      "assigned_task_count": len(list_value(object_value(state.get("dynamic_workflow_plan")).get("tasks"))),
    },
    {
      "status": specialist_results.get("status"),
      "completed_task_ids": list_value(specialist_results.get("completed_task_ids")),
      "result_count": len(object_value(specialist_results.get("results"))),
    },
  )
  safety_violations = [
    violation
    for execution in state["dynamic_agent_executions"]
    if isinstance(execution, dict)
    for violation in list_value(execution.get("safety_violations"))
  ]
  failed_execution_agent_ids = unique_paths(
    [
      text_or_default(execution.get("agent_id"), "")
      for execution in state["dynamic_agent_executions"]
      if isinstance(execution, dict) and execution.get("execution_failed")
    ]
  )
  assignments = list_value(object_value(state.get("dynamic_workflow_plan")).get("assignments"))
  violating_agent_ids: list[str] = []
  if safety_violations:
    violating_agent_ids = unique_paths(
      [
        text_or_default(execution.get("agent_id"), "")
        for execution in state["dynamic_agent_executions"]
        if isinstance(execution, dict) and list_value(execution.get("safety_violations"))
      ]
    )
    violating_assignments = [
      assignment
      for assignment in assignments
      if isinstance(assignment, dict) and text_or_default(assignment.get("agent_id"), "") in violating_agent_ids
    ]
    registry.mark_workflow_failure(
      violating_assignments,
      reason="; ".join(str(item) for item in safety_violations)[:1200],
      safety_violation=True,
    )
    state["dynamic_agent_lifecycle_decisions"].append(
      {"type": "safety_violation", "agent_ids": violating_agent_ids, "reasons": safety_violations}
    )
  failed_execution_agent_ids = [
    agent_id for agent_id in failed_execution_agent_ids if agent_id not in set(violating_agent_ids)
  ]
  if failed_execution_agent_ids:
    failure_assignments = [
      assignment
      for assignment in assignments
      if isinstance(assignment, dict) and text_or_default(assignment.get("agent_id"), "") in failed_execution_agent_ids
    ]
    failure_reasons = [
      text_or_default(execution.get("fallback_reason"), "")
      for execution in state["dynamic_agent_executions"]
      if isinstance(execution, dict)
      and execution.get("execution_failed")
      and text_or_default(execution.get("agent_id"), "") in failed_execution_agent_ids
    ]
    registry.mark_workflow_failure(
      failure_assignments,
      reason="; ".join(reason for reason in failure_reasons if reason)[:1200] or "Dynamic agent execution failed.",
    )
    state["dynamic_agent_lifecycle_decisions"].append(
      {"type": "execution_failure", "agent_ids": failed_execution_agent_ids, "reasons": failure_reasons}
    )
  active_agent_ids = [
    text_or_default(item.get("agent_id"), "")
    for item in assignments
    if isinstance(item, dict)
  ]
  persist_user_dynamic_agents(
    getattr(tool_context, "store", None),
    user,
    registry,
    agent_ids=active_agent_ids,
  )
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_dynamic_specialists",
    kind="specialist_results",
    content=specialist_results,
    project_id=project_id,
  )
  return

def handle_dynamic_patch_integrator(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  candidate_files = list(state.get("candidate_files") or [])
  accepted_changes = list_value(state.get("candidate_changes"))
  integration_result = integrate_dynamic_candidate_changes(candidate_files, accepted_changes)
  state["candidate_files"] = integration_result["files"]
  state["dynamic_patch_integrated"] = True
  summary = {
    **object_value(state.get("candidate_change_summary")),
    "integration_status": integration_result["status"],
    "integrated_paths": integration_result["integrated_paths"],
    "rejected_conflicts": integration_result["rejected_conflicts"],
  }
  state["candidate_change_summary"] = summary
  state["changed_file_paths"] = unique_paths(
    [*list(state.get("changed_file_paths") or []), *integration_result["integrated_paths"]]
  )
  sync_generated_website_files_from_candidates(state)
  state["files_materialized"] = False
  state["materialized_file_paths"] = []
  state["materialized_file_signatures"] = {}
  state["committed"] = False
  append_step(
    state,
    agent,
    "integrate_dynamic_candidate_changes",
    {"candidate_change_count": len(accepted_changes)},
    summary,
  )
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="dynamic_patch_integrated",
    message_prefix="Prepared integrated code changes",
  )
  log_dynamic_agent_event(
    "candidate_changes.integrated",
    status=integration_result["status"],
    payload=summary,
  )
  return
