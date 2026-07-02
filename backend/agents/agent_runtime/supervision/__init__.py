from __future__ import annotations

import os
import re
from typing import Any

try:
  from ....audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ...dynamic_agents import AgentRegistry, CapabilityTask, runtime_agent_name_for_action
from ...runtime_agents.registry import ACTION_REGISTRY
from ..compaction import compact_dynamic_specialist_results_for_prompt, compact_dynamic_workflow_for_prompt
from ..constants import SCOPED_UPDATE_MAX_NEW_FILES, SCOPED_UPDATE_MAX_TASKS, SUPERVISOR_SYSTEM_INSTRUCTION
from ..errors import AgentRuntimeLoopError
from ..file_ops import unique_paths
from ..progress import completion_status
from ..prompts import build_supervisor_decision_prompt
from ..state import append_step
from ..materialize import all_candidate_files, pending_materialization_files
from ..values import list_value, object_value, string_list, text_or_default


def available_runtime_actions(state: dict[str, Any], *, max_repair_attempts: int) -> list[dict[str, Any]]:
  if not state.get("read_result") or not state.get("memory_result"):
    if runtime_parallel_actions_enabled() and not state.get("read_result") and not state.get("memory_result"):
      return action_options(["RUN_PARALLEL_PROJECT_BOOTSTRAP"])
    if not state.get("read_result"):
      return action_options(["READ_PROJECT_FILES"])
    if not state.get("memory_result"):
      return action_options(["LOAD_PROJECT_MEMORY"])
  if (
    state.get("operation") == "update"
    and not state.get("generated_website")
    and not state.get("update_analysis")
    and not state.get("error_diagnosis")
  ):
    return action_options(["RUN_UPDATE_ANALYST", "RUN_ERROR_HANDLING_AGENT"], state=state)
  if state.get("operation") == "update" and not state.get("generated_website") and not state.get("update_analysis"):
    return action_options(["RUN_UPDATE_ANALYST"])
  if is_agentic_scoped_update_mode(state):
    if not state.get("dynamic_workflow_plan"):
      return action_options(["RUN_DYNAMIC_AGENT_PLANNER"])
    if not state.get("dynamic_specialists_completed"):
      return action_options(["RUN_DYNAMIC_SPECIALISTS"], state=state)
    if not state.get("generated_website"):
      return action_options(["RUN_SCOPED_UPDATE_AGENT"], state=state)
    return available_finalization_actions(state, max_repair_attempts=max_repair_attempts)
  if is_scoped_update_mode(state):
    if not state.get("generated_website"):
      return action_options(["RUN_SCOPED_UPDATE_AGENT"], state=state)
    return available_finalization_actions(state, max_repair_attempts=max_repair_attempts)
  if not state.get("brief"):
    return action_options(["RUN_PROMPT_ANALYST"])
  if not state.get("dynamic_workflow_plan"):
    if should_use_direct_generation_workflow(state):
      apply_direct_generation_workflow(state)
    else:
      return action_options(["RUN_DYNAMIC_AGENT_PLANNER"])
  if not state.get("plan"):
    return action_options(["RUN_PLANNER"], state=state)
  if not state.get("dynamic_specialists_completed"):
    return action_options(["RUN_DYNAMIC_SPECIALISTS"], state=state)
  if not state.get("ux_review") and not state.get("accessibility_review"):
    if runtime_parallel_actions_enabled():
      return action_options(["RUN_PARALLEL_REVIEW_AGENTS"], state=state)
    return action_options(["RUN_UX_REVIEW_AGENT", "RUN_ACCESSIBILITY_AGENT"], state=state)
  if not state.get("ux_review"):
    return action_options(["RUN_UX_REVIEW_AGENT"], state=state)
  if not state.get("accessibility_review"):
    return action_options(["RUN_ACCESSIBILITY_AGENT"], state=state)

  return available_finalization_actions(state, max_repair_attempts=max_repair_attempts)


def full_dynamic_generation_enabled() -> bool:
  try:
    from ..runtime_config import full_dynamic_generation_enabled as parity_full_dynamic_enabled
    return parity_full_dynamic_enabled()
  except ImportError:
    from ...runtime_config import full_dynamic_generation_enabled as parity_full_dynamic_enabled
    return parity_full_dynamic_enabled()


def runtime_parallel_actions_enabled() -> bool:
  try:
    from ..runtime_config import runtime_parallel_actions_enabled as parity_parallel_enabled
    return parity_parallel_enabled()
  except ImportError:
    from ...runtime_config import runtime_parallel_actions_enabled as parity_parallel_enabled
    return parity_parallel_enabled()


def should_use_direct_generation_workflow(state: dict[str, Any]) -> bool:
  if state.get("operation") != "generate":
    return False
  return not full_dynamic_generation_enabled()


def apply_direct_generation_workflow(state: dict[str, Any]) -> dict[str, Any]:
  workflow_plan = build_direct_generation_workflow(state)
  state["dynamic_workflow_plan"] = workflow_plan
  state["dynamic_specialists_completed"] = True
  state["dynamic_specialist_results"] = {
    "status": "skipped",
    "source": "model_routed_direct_generation_policy",
    "reason": "The chief orchestrator already selected website_generation, so no spawned specialist agents were needed for this normal generation run.",
    "completed_task_ids": [],
    "parallel_groups_executed": [],
    "results": {},
    "dynamic_agent_executions": [],
    "candidate_changes": [],
    "candidate_change_summary": {"accepted_count": 0, "rejected_count": 0, "accepted": [], "rejected": []},
  }
  state["candidate_changes"] = []
  state["candidate_change_summary"] = {"accepted_count": 0, "rejected_count": 0, "accepted": [], "rejected": []}
  state["dynamic_patch_integrated"] = True
  state["ux_review"] = skipped_direct_generation_review("UX Review Agent")
  state["accessibility_review"] = skipped_direct_generation_review("Accessibility Agent")
  return workflow_plan


def build_direct_generation_workflow(state: dict[str, Any]) -> dict[str, Any]:
  routing_result = object_value(state.get("routing_result"))
  brief = object_value(state.get("brief"))
  return {
    "domain": "website_generation",
    "scope": "direct_generation",
    "tasks": [
      {
        "id": "implementation_plan",
        "name": "Implementation plan",
        "required_capability": "project_planning",
        "description": "Create the website implementation plan from the structured brief.",
        "dependencies": [],
        "risk_level": "low",
        "runtime_action": "RUN_PLANNER",
      },
      {
        "id": "code_generation",
        "name": "Code generation",
        "required_capability": "react_tailwind_development",
        "description": "Generate the complete project artifact after the plan is ready.",
        "dependencies": ["implementation_plan"],
        "risk_level": "medium",
        "runtime_action": "RUN_CODE_AGENT",
      },
    ],
    "assignments": [],
    "dependency_graph": {"implementation_plan": [], "code_generation": ["implementation_plan"]},
    "parallel_groups": [["implementation_plan"], ["code_generation"]],
    "completion_proof": [
      "Chief Orchestrator selected the website_generation route.",
      "Normal generation uses the minimum capable workflow: brief, plan, code, validation, preview, QA, write, memory.",
      "Dynamic specialists and extra review agents are skipped unless ENABLE_FULL_DYNAMIC_GENERATION=true.",
    ],
    "active_agents": [],
    "created_agent_ids": [],
    "reused_agent_ids": [],
    "planning_source": "model_routed_direct_generation_policy",
    "planner_reason": (
      "The model routed this turn to website_generation. The runtime selected the smallest safe "
      "workflow so confirmed briefs generate files directly instead of spending minutes in optional "
      "specialist and review agents."
    ),
    "routing_intent": text_or_default(routing_result.get("intent"), ""),
    "brief_title": text_or_default(brief.get("title"), text_or_default(brief.get("project_title"), "")),
  }


def skipped_direct_generation_review(agent_name: str) -> dict[str, Any]:
  return {
    "status": "skipped",
    "agent": agent_name,
    "source": "model_routed_direct_generation_policy",
    "issues": [],
    "recommendations": [],
    "control_fallback": {
      "source": "model_routed_direct_generation_policy",
      "reason": "Normal website generation uses direct planning and artifact generation; optional review agents are disabled by default for latency.",
    },
  }


def available_finalization_actions(state: dict[str, Any], *, max_repair_attempts: int) -> list[dict[str, Any]]:
  preview_status = object_value(object_value(state.get("preview_result")).get("version")).get("status")
  validation_status = object_value(state.get("validation_result")).get("status")
  visual_qa_status = object_value(state.get("visual_qa_result")).get("status")
  visual_qa_failed = bool(visual_qa_status) and visual_qa_status != "passed"
  needs_repair = bool(state.get("repair_errors")) and (preview_status != "ready" or visual_qa_failed)
  if needs_repair and is_scoped_update_mode(state):
    if state.get("repair_attempts", 0) < max_repair_attempts:
      return action_options(["RUN_SCOPED_UPDATE_AGENT"], state=state)
    return []
  if needs_repair and state.get("repair_attempts", 0) < max_repair_attempts:
    return action_options(["RUN_REPAIR_AGENT"], state=state)
  if needs_repair and state.get("repair_attempts", 0) >= max_repair_attempts:
    return []

  if not state.get("generated_website"):
    return action_options(["RUN_CODE_AGENT"], state=state)
  if dynamic_patch_integration_required(state) and not state.get("dynamic_patch_integrated"):
    return action_options(["RUN_DYNAMIC_PATCH_INTEGRATOR"], state=state)
  if pending_materialization_files(state) or (
    all_candidate_files(state) and not state.get("files_materialized")
  ):
    return action_options(["MATERIALIZE_CANDIDATE_FILES"], state=state)
  if validation_status != "valid":
    return action_options(["VALIDATE_PROJECT_ARTIFACT"], state=state)
  if preview_status != "ready":
    return action_options(["BUILD_STAGED_PROJECT_PREVIEW"], state=state)
  if object_value(state.get("visual_qa_result")).get("status") != "passed":
    return action_options(["RUN_PREVIEW_VISUAL_QA"], state=state)
  if not state.get("memory"):
    return action_options(["PERSIST_PROJECT_MEMORY"], state=state)
  return action_options(["DONE"])


def dynamic_patch_integration_required(state: dict[str, Any]) -> bool:
  return bool(list_value(state.get("candidate_changes")))


def is_scoped_update_mode(state: dict[str, Any]) -> bool:
  if state.get("operation") != "update":
    return False
  return text_or_default(object_value(state.get("update_analysis")).get("update_mode"), "") in {
    "targeted_patch",
    "bug_fix",
    "feature_patch",
  }


def is_agentic_scoped_update_mode(state: dict[str, Any]) -> bool:
  if not is_scoped_update_mode(state):
    return False
  analysis = object_value(state.get("update_analysis"))
  if text_or_default(analysis.get("update_mode"), "") != "feature_patch":
    return False
  return scoped_update_needs_dynamic_agents(analysis)


def scoped_update_needs_dynamic_agents(update_analysis: dict[str, Any]) -> bool:
  if text_or_default(update_analysis.get("execution_strategy"), "") == "deterministic_patch":
    return False
  if text_or_default(update_analysis.get("scope"), "small") in {"medium", "large"}:
    return True
  if len(list_value(update_analysis.get("scoped_update_tasks"))) >= 3:
    return True
  feature_plan = object_value(update_analysis.get("feature_plan"))
  if len(string_list(feature_plan.get("items"), [])) >= 3:
    return True
  return False


def scoped_update_used_dynamic_agents(state: dict[str, Any]) -> bool:
  return "RUN_DYNAMIC_AGENT_PLANNER" in list_value(state.get("action_history")) or bool(
    object_value(state.get("dynamic_workflow_plan")).get("active_agents")
    and object_value(state.get("dynamic_specialist_results")).get("status") == "completed"
  )


def update_analysis_with_agentic_context(update_analysis: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
  if not scoped_update_used_dynamic_agents(state):
    return update_analysis
  workflow = compact_dynamic_workflow_for_prompt(state.get("dynamic_workflow_plan"))
  specialist_results = compact_dynamic_specialist_results_for_prompt(state.get("dynamic_specialist_results"))
  return {
    **update_analysis,
    "agentic_dynamic_context": {
      "workflow": workflow,
      "specialist_results": specialist_results,
    },
  }


def is_scoped_update_dynamic_workflow(workflow_plan: Any) -> bool:
  return text_or_default(object_value(workflow_plan).get("planning_source"), "") == "scoped_update_registry_reuse"


def build_scoped_update_dynamic_workflow(
  update_analysis: dict[str, Any],
  *,
  registry: AgentRegistry,
) -> dict[str, Any]:
  source_tasks = [
    task
    for task in list_value(update_analysis.get("scoped_update_tasks"))
    if isinstance(task, dict)
  ][:SCOPED_UPDATE_MAX_TASKS]
  if not source_tasks:
    source_tasks = [
      {
        "id": "scoped_feature_patch",
        "summary": text_or_default(update_analysis.get("summary"), "Apply the scoped feature update."),
        "prompt": text_or_default(update_analysis.get("summary"), "Apply the scoped feature update."),
        "candidate_files": string_list(update_analysis.get("candidate_files"), []),
        "candidate_new_files": string_list(update_analysis.get("candidate_new_files"), []),
        "target_symbols": string_list(update_analysis.get("target_symbols"), []),
      }
    ]

  capability_tasks: list[CapabilityTask] = []
  for index, source_task in enumerate(source_tasks):
    task_id = normalize_scoped_dynamic_task_id(source_task.get("id"), fallback=f"scoped_step_{index + 1}")
    dependencies = [capability_tasks[-1].id] if capability_tasks else []
    summary = text_or_default(source_task.get("summary"), f"Scoped update step {index + 1}")
    prompt = text_or_default(source_task.get("prompt"), summary)
    capability_tasks.append(
      CapabilityTask(
        id=task_id,
        name=summary[:90] or f"Scoped update step {index + 1}",
        required_capability="component_plan",
        description=prompt[:900] or summary[:900],
        input_schema={
          "type": "object",
          "candidate_files": string_list(source_task.get("candidate_files"), []),
          "candidate_new_files": string_list(source_task.get("candidate_new_files"), []),
          "target_symbols": string_list(source_task.get("target_symbols"), []),
        },
        output_schema={
          "type": "object",
          "properties": {
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "requirements": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
          },
        },
        dependencies=dependencies,
        risk_level=text_or_default(update_analysis.get("scope"), "medium")
        if text_or_default(update_analysis.get("scope"), "medium") in {"low", "medium", "high"}
        else "medium",
        runtime_action="RUN_DYNAMIC_SPECIALISTS",
      )
    )

  assignments, created_ids, reused_ids = registry.assign_tasks(
    capability_tasks,
    domain="website_update",
    provider=None,
    max_dynamic_agents=0,
  )
  assignment_by_task = {assignment.task_id: assignment for assignment in assignments}
  active_agent_ids = unique_paths([assignment.agent_id for assignment in assignments])
  active_agents: list[dict[str, Any]] = []
  for agent_id in active_agent_ids:
    definition = registry.agents.get(agent_id)
    if not definition:
      continue
    active_agents.append(
      {
        "id": definition.id,
        "name": definition.name,
        "role": definition.role,
        "capabilities": definition.capabilities,
        "lifecycle": definition.lifecycle,
        "assigned_tasks": [
          task.id
          for task in capability_tasks
          if assignment_by_task.get(task.id) and assignment_by_task[task.id].agent_id == agent_id
        ],
      }
    )

  task_dicts: list[dict[str, Any]] = []
  for task in capability_tasks:
    task_dict = task.to_dict()
    assignment = assignment_by_task.get(task.id)
    if assignment:
      task_dict["agent_id"] = assignment.agent_id
      task_dict["agent_name"] = assignment.agent_name
    task_dicts.append(task_dict)

  return {
    "domain": "website_update",
    "scope": "scoped_feature_patch",
    "tasks": task_dicts,
    "assignments": [assignment.to_dict() for assignment in assignments],
    "dependency_graph": {task.id: list(task.dependencies) for task in capability_tasks},
    "parallel_groups": [[task.id] for task in capability_tasks],
    "completion_proof": [
      "Reusable scoped-update agent workflow selected from the registry.",
      "Scoped patch agent receives compact workflow guidance before editing approved files.",
      "Validation, staged preview, visual QA, and memory persistence must still pass.",
    ],
    "active_agents": active_agents,
    "created_agent_ids": created_ids,
    "reused_agent_ids": reused_ids,
    "planning_source": "scoped_update_registry_reuse",
    "planner_reason": (
      "This is an approved-file scoped website update, so the runtime reused the dynamic "
      "agent registry and skipped broad research/decomposition/planner model calls."
    ),
  }


def normalize_scoped_dynamic_task_id(value: Any, *, fallback: str) -> str:
  raw = text_or_default(value, fallback)
  task_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw).strip("_").lower()
  return (task_id or fallback)[:48]


def build_scoped_update_dynamic_specialist_results(
  workflow_plan: dict[str, Any],
  update_analysis: dict[str, Any],
) -> dict[str, Any]:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  feature_items = string_list(feature_plan.get("items"), [])
  preserve_rules = string_list(update_analysis.get("preserve_rules"), [])
  assignment_by_task = {
    text_or_default(assignment.get("task_id"), ""): assignment
    for assignment in list_value(workflow_plan.get("assignments"))
    if isinstance(assignment, dict)
  }
  results: dict[str, dict[str, Any]] = {}
  executions: list[dict[str, Any]] = []
  completed_task_ids: list[str] = []
  for task in list_value(workflow_plan.get("tasks")):
    if not isinstance(task, dict):
      continue
    task_id = text_or_default(task.get("id"), "")
    if not task_id:
      continue
    assignment = object_value(assignment_by_task.get(task_id))
    input_schema = object_value(task.get("input_schema"))
    candidate_files = string_list(input_schema.get("candidate_files"), [])
    candidate_new_files = string_list(input_schema.get("candidate_new_files"), [])
    requirements = [
      text_or_default(task.get("description"), text_or_default(task.get("name"), "Apply scoped feature step.")),
      *feature_items[:8],
    ]
    recommendations = [
      "Patch only the approved existing files for this scoped task.",
      "Keep unrelated modules, navigation, data flow, and styling stable.",
    ]
    if candidate_files:
      recommendations.append(f"Approved existing files: {', '.join(candidate_files[:4])}.")
    if candidate_new_files:
      recommendations.append(f"Approved new files: {', '.join(candidate_new_files[:SCOPED_UPDATE_MAX_NEW_FILES])}.")
    risks = preserve_rules[:3] or ["Avoid broad rewrites and preserve current project behavior."]
    results[task_id] = {
      "status": "completed",
      "source": "scoped_update_registry_reuse",
      "agent": text_or_default(assignment.get("agent_name"), "Component/UI Agent"),
      "agent_id": text_or_default(assignment.get("agent_id"), "component-ui-agent"),
      "summary": text_or_default(task.get("name"), "Prepared scoped update guidance."),
      "recommendations": recommendations[:6],
      "requirements": [item for item in requirements if item][:10],
      "risks": risks,
      "candidate_changes": [],
    }
    executions.append(
      {
        "task_id": task_id,
        "agent_id": text_or_default(assignment.get("agent_id"), "component-ui-agent"),
        "agent_name": text_or_default(assignment.get("agent_name"), "Component/UI Agent"),
        "status": "completed",
        "source": "scoped_update_registry_reuse",
        "duration_ms": 0,
        "execution_failed": False,
        "fallback_reason": "",
        "safety_violations": [],
      }
    )
    completed_task_ids.append(task_id)
  return {
    "status": "completed",
    "source": "scoped_update_registry_reuse",
    "completed_task_ids": completed_task_ids,
    "parallel_groups_executed": list_value(workflow_plan.get("parallel_groups")),
    "results": results,
    "dynamic_agent_executions": executions,
    "candidate_changes": [],
    "candidate_change_summary": {"accepted_count": 0, "rejected_count": 0, "accepted": [], "rejected": []},
  }


def effective_repair_attempt_budget(max_repair_attempts: int) -> int:
  try:
    value = int(max_repair_attempts)
  except (TypeError, ValueError):
    value = 1
  return max(0, min(value, 1))


def action_options(action_names: list[str], *, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
  options: list[dict[str, Any]] = []
  workflow_plan = object_value(object_value(state).get("dynamic_workflow_plan"))
  for name in action_names:
    definition = ACTION_REGISTRY[name]
    options.append(
      {
        "name": name,
        "agent": runtime_agent_name_for_action(workflow_plan, name, definition["agent"]),
        "description": definition["description"],
        "tools": definition["tools"],
      }
    )
  return options


def supervisor_choose_next_action(
  state: dict[str, Any],
  *,
  supervisor_provider: Any | None = None,
  goal: str,
  available_actions: list[dict[str, Any]],
  available_tools: list[dict[str, Any]],
) -> dict[str, Any]:
  if not available_actions:
    raise AgentRuntimeLoopError("No legal supervisor actions are available for the current state.")
  policy_action = available_actions[0]
  model_supervisor_forced = bool(getattr(supervisor_provider, "force_model_supervisor", False))
  if should_use_model_supervisor(supervisor_provider):
    model_output = run_supervisor_model_decision(
      supervisor_provider,
      state,
      goal=goal,
      available_actions=available_actions,
      available_tools=available_tools,
    )
    decision = normalize_supervisor_decision(
      model_output,
      available_actions=available_actions,
      policy_action=policy_action,
      model_supervisor_forced=model_supervisor_forced,
    )
  else:
    model_output = None
    decision = {
      **decision_from_action(policy_action, reason="Python supervisor policy selected the next safe legal action."),
      "decision_source": "policy",
      "guardrail_status": "validated",
      "guardrail_reason": "Model supervisor disabled for deterministic runtime efficiency.",
    }
  audit_entry = build_supervisor_audit_entry(
    state,
    decision=decision,
    model_output=model_output,
    available_actions=available_actions,
    policy_action=policy_action,
  )
  decision["audit_id"] = audit_entry["audit_id"]
  state["supervisor_audit_trail"].append(audit_entry)
  log_query_event(
    "supervisor.decision",
    status="completed" if decision["decision_source"] in {"model", "policy"} else "degraded",
    payload=audit_entry,
  )
  if decision["decision_source"] == "policy_fallback":
    state["supervisor_policy_fallbacks"].append(
      {
        "audit_id": audit_entry["audit_id"],
        "policy_action": policy_action,
        "model_output": model_output,
        "fallback_reason": decision.get("guardrail_reason"),
      }
    )
  state["supervisor_decisions"].append(decision)
  append_step(
    state,
    "Supervisor Agent",
    "choose_next_agent",
    {
      "current_step_count": len(state["agent_steps"]),
      "last_tool_status": last_tool_status(state),
      "goal": goal,
      "available_actions": available_actions,
      "completion_status": completion_status(state),
    },
    decision,
    tool_calls=[],
  )
  state["messages"].append(
    {
      "from_agent": "Supervisor Agent",
      "to_agent": decision["next_agent"],
      "content": decision["reason"],
      "next_action": decision["next_action"],
      "decision_source": decision["decision_source"],
    }
  )
  return decision


def should_use_model_supervisor(supervisor_provider: Any | None) -> bool:
  if supervisor_provider is None or not hasattr(supervisor_provider, "generate_json"):
    return False
  if getattr(supervisor_provider, "force_model_supervisor", False):
    return True
  try:
    from ..runtime_config import gemini_supervisor_enabled
  except ImportError:
    from ...runtime_config import gemini_supervisor_enabled
  return gemini_supervisor_enabled()


def build_supervisor_audit_entry(
  state: dict[str, Any],
  *,
  decision: dict[str, Any],
  model_output: dict[str, Any] | None,
  available_actions: list[dict[str, Any]],
  policy_action: dict[str, Any],
) -> dict[str, Any]:
  legal_action_names = [str(action.get("name")) for action in available_actions if isinstance(action, dict)]
  required_tools_by_action = {
    str(action.get("name")): list(action.get("tools") or [])
    for action in available_actions
    if isinstance(action, dict) and action.get("name")
  }
  selected_action = text_or_default(decision.get("next_action"), "")
  completion = completion_status(state)
  return {
    "audit_id": f"supervisor-{len(state.get('supervisor_audit_trail') or []) + 1:03d}",
    "decision_source": decision.get("decision_source"),
    "guardrail_status": decision.get("guardrail_status"),
    "guardrail_reason": decision.get("guardrail_reason"),
    "selected_agent": decision.get("next_agent"),
    "selected_action": selected_action,
    "selected_action_is_legal": selected_action in legal_action_names,
    "selected_required_tools": required_tools_by_action.get(selected_action, []),
    "selected_tools_to_call": list(decision.get("tools_to_call") or []),
    "policy_action": policy_action.get("name"),
    "legal_actions": legal_action_names,
    "required_tools_by_action": required_tools_by_action,
    "model_output": safe_supervisor_output(model_output) if isinstance(model_output, dict) else model_output,
    "completion_status_before": completion,
    "completion_proof_before": all(completion.values()),
    "last_tool_status": last_tool_status(state),
    "recent_observations": recent_observations(state, limit=4),
  }


def mark_supervisor_audit_completion_rejected(state: dict[str, Any], rejection: dict[str, Any]) -> None:
  audit_id = rejection.get("audit_id")
  for entry in reversed(state.get("supervisor_audit_trail") or []):
    if isinstance(entry, dict) and entry.get("audit_id") == audit_id:
      entry["completion_rejected"] = True
      entry["completion_rejection_reason"] = rejection.get("reason")
      entry["completion_status_after_rejection"] = rejection.get("completion_status")
      return


def run_supervisor_model_decision(
  supervisor_provider: Any | None,
  state: dict[str, Any],
  *,
  goal: str,
  available_actions: list[dict[str, Any]],
  available_tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
  if supervisor_provider is None or not hasattr(supervisor_provider, "generate_json"):
    return None
  prompt = build_supervisor_decision_prompt(
    goal=goal,
    available_actions=available_actions,
    compact_tools=compact_tool_schemas(available_tools),
    state_summary=supervisor_state_summary(state),
    recent_observations=recent_observations(state),
  )
  try:
    response = supervisor_provider.generate_json(
      prompt,
      system_instruction=SUPERVISOR_SYSTEM_INSTRUCTION,
      trace_label="supervisor_agent",
    )
  except Exception as exc:
    return {"error": str(exc), "decision_source": "model_error"}
  return response if isinstance(response, dict) else {"raw_output": response}


def supervisor_state_summary(state: dict[str, Any]) -> dict[str, Any]:
  preview = state.get("preview")
  return {
    "project_id": state.get("project_id"),
    "routing_intent": object_value(state.get("routing_result")).get("intent"),
    "operation": state.get("operation"),
    "brief_ready": isinstance(state.get("brief"), dict),
    "dynamic_workflow_ready": isinstance(state.get("dynamic_workflow_plan"), dict),
    "dynamic_specialists_completed": bool(state.get("dynamic_specialists_completed")),
    "plan_ready": isinstance(state.get("plan"), dict),
    "generated_file_count": len(state.get("files") or []),
    "loaded_memory_count": len(state.get("loaded_memory") or []),
    "preview_status": object_value(preview).get("status") if isinstance(preview, dict) else None,
    "visual_qa_status": object_value(state.get("visual_qa_result")).get("status"),
    "validation_status": object_value(state.get("validation_result")).get("status"),
    "committed": bool(state.get("committed")),
    "memory_prepared": bool(state.get("memory")),
    "repair_attempts": int(state.get("repair_attempts") or 0),
    "last_tool_status": last_tool_status(state),
    "tool_call_count": len(state.get("tool_calls") or []),
  }


def normalize_supervisor_decision(
  model_output: dict[str, Any] | None,
  *,
  available_actions: list[dict[str, Any]],
  policy_action: dict[str, Any],
  model_supervisor_forced: bool = False,
) -> dict[str, Any]:
  legal_by_action = {option["name"]: option for option in available_actions}
  policy_decision = decision_from_action(policy_action, reason="Policy selected the next safe legal action.")
  if model_output is None:
    return {
      **policy_decision,
      "decision_source": "policy",
      "guardrail_status": "validated",
      "guardrail_reason": "No model supervisor decision was requested; policy selected the next safe legal action.",
    }
  if isinstance(model_output, dict) and model_output.get("error") and not model_supervisor_forced:
    return {
      **policy_decision,
      "decision_source": "policy",
      "guardrail_status": "validated",
      "guardrail_reason": "Optional model supervisor was unavailable; policy selected the next safe legal action.",
      "model_output": safe_supervisor_output(model_output),
    }
  if not isinstance(model_output, dict) and not model_supervisor_forced:
    return {
      **policy_decision,
      "decision_source": "policy",
      "guardrail_status": "validated",
      "guardrail_reason": "Optional model supervisor returned no usable decision; policy selected the next safe legal action.",
    }
  if not isinstance(model_output, dict) or model_output.get("error"):
    return {
      **policy_decision,
      "decision_source": "policy_fallback",
      "guardrail_status": "fallback",
      "guardrail_reason": text_or_default(object_value(model_output).get("error"), "No model supervisor decision was available."),
    }

  chosen_action = text_or_default(model_output.get("next_action"), "")
  action_option = legal_by_action.get(chosen_action)
  if not action_option:
    return {
      **policy_decision,
      "decision_source": "policy_fallback",
      "guardrail_status": "fallback",
      "guardrail_reason": "Model supervisor chose an action outside the current legal action set.",
      "model_output": safe_supervisor_output(model_output),
    }
  chosen_agent = text_or_default(model_output.get("next_agent"), action_option["agent"])
  if chosen_agent != action_option["agent"]:
    return {
      **policy_decision,
      "decision_source": "policy_fallback",
      "guardrail_status": "fallback",
      "guardrail_reason": "Model supervisor chose an agent that does not own the selected action.",
      "model_output": safe_supervisor_output(model_output),
    }

  requested_tools = string_list(model_output.get("tools_to_call") or model_output.get("tool_calls"), [])
  required_tools = list(action_option.get("tools") or [])
  missing_required_tools = [tool for tool in required_tools if tool not in requested_tools]
  if missing_required_tools:
    return {
      **policy_decision,
      "decision_source": "policy_fallback",
      "guardrail_status": "fallback",
      "guardrail_reason": "Model supervisor did not request the required backend tools for the selected action.",
      "model_output": safe_supervisor_output(model_output),
    }
  if any(tool not in required_tools for tool in requested_tools):
    return {
      **policy_decision,
      "decision_source": "policy_fallback",
      "guardrail_status": "fallback",
      "guardrail_reason": "Model supervisor requested a backend tool that is not allowed for the selected action.",
      "model_output": safe_supervisor_output(model_output),
    }
  return {
    "next_agent": chosen_agent,
    "next_action": chosen_action,
    "reason": text_or_default(model_output.get("reason"), action_option["description"]),
    "tools_to_call": required_tools,
    "stop_or_continue": "done" if chosen_action == "DONE" else "continue",
    "decision_source": "model",
    "guardrail_status": "validated",
    "model_output": safe_supervisor_output(model_output),
  }


def decision_from_action(action_option: dict[str, Any], *, reason: str) -> dict[str, Any]:
  action = action_option["name"]
  return {
    "next_agent": action_option["agent"],
    "next_action": action,
    "reason": reason,
    "tools_to_call": list(action_option.get("tools") or []),
    "stop_or_continue": "done" if action == "DONE" else "continue",
  }


def safe_supervisor_output(model_output: dict[str, Any]) -> dict[str, Any]:
  tools_to_call = model_output.get("tools_to_call")
  if tools_to_call is None:
    tools_to_call = model_output.get("tool_calls")
  return {
    "next_agent": model_output.get("next_agent"),
    "next_action": model_output.get("next_action"),
    "reason": model_output.get("reason"),
    "tools_to_call": tools_to_call,
    "stop_or_continue": model_output.get("stop_or_continue"),
  }


def compact_tool_schemas(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
  return [
    {
      "name": tool.get("name"),
      "description": tool.get("description"),
      "parameters": tool.get("parameters"),
    }
    for tool in tools
    if isinstance(tool, dict)
  ]


def recent_observations(state: dict[str, Any], *, limit: int = 6) -> list[dict[str, Any]]:
  observations = []
  for step in list(state.get("agent_steps") or [])[-limit:]:
    if not isinstance(step, dict):
      continue
    observations.append(
      {
        "agent": step.get("agent"),
        "action": step.get("action"),
        "status": step.get("status"),
        "tool_calls": step.get("tool_calls"),
      }
    )
  return observations


def last_tool_status(state: dict[str, Any]) -> str | None:
  tool_calls = state.get("tool_calls")
  if not isinstance(tool_calls, list) or not tool_calls:
    return None
  latest = tool_calls[-1]
  return str(latest.get("status")) if isinstance(latest, dict) and latest.get("status") else None
