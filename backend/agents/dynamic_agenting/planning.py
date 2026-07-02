from __future__ import annotations

import json
import re
from typing import Any

from ..prompts import build_task_decomposition_prompt, build_workflow_planning_prompt
try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block
from .constants import MAX_DYNAMIC_AGENTS_PER_WORKFLOW, MODEL_DYNAMIC_TASK_LIMIT
from .models import AgentAssignment, CapabilityTask, WorkflowPlan
from .policy import is_non_creatable_agent_capability
from .registry import AgentRegistry
from .utils import object_value, slug, string_list, text_value, title_name, unique_strings


def create_dynamic_workflow(
  prompt: str,
  *,
  routing_result: dict[str, Any],
  brief: dict[str, Any],
  provider: Any | None = None,
  registry: AgentRegistry | None = None,
) -> dict[str, Any]:
  registry = registry or AgentRegistry()
  domain = infer_dynamic_domain(prompt, brief)
  scope = infer_scope(prompt, brief)
  deterministic_tasks = decompose_capability_tasks(prompt, domain=domain, scope=scope)
  model_tasks = request_model_task_decomposition(provider, prompt, routing_result=routing_result, brief=brief)
  tasks = merge_capability_tasks(deterministic_tasks, model_tasks, domain=domain)
  assignments, created_ids, reused_ids = registry.assign_tasks(tasks, domain=domain, provider=provider)
  deterministic_parallel_groups = build_parallel_groups(tasks)
  model_workflow = request_model_workflow_plan(provider, tasks, assignments)
  model_parallel_groups = validate_parallel_groups(model_workflow.get("parallel_groups"), tasks)
  parallel_groups = model_parallel_groups or deterministic_parallel_groups
  assignment_by_task = {assignment.task_id: assignment for assignment in assignments}
  active_agent_ids = unique_strings([assignment.agent_id for assignment in assignments])
  active_agents = []
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
          for task in tasks
          if assignment_by_task.get(task.id) and assignment_by_task[task.id].agent_id == agent_id
        ],
      }
    )
  plan = WorkflowPlan(
    domain=domain,
    scope=scope,
    tasks=tasks,
    assignments=assignments,
    dependency_graph={task.id: list(task.dependencies) for task in tasks},
    parallel_groups=parallel_groups,
    completion_proof=[
      "artifact_valid",
      "staged_preview_ready",
      "visual_qa_passed",
      "files_committed",
      "memory_prepared",
    ],
    active_agents=active_agents,
    created_agent_ids=created_ids,
    reused_agent_ids=reused_ids,
    planning_source=(
      "gemini_guarded_decomposition_and_workflow"
      if model_tasks and model_parallel_groups
      else "gemini_guarded_decomposition"
      if model_tasks
      else "gemini_guarded_workflow"
      if model_parallel_groups
      else "python_guardrail"
    ),
    planner_reason=text_value(model_workflow.get("reason")) or "Python produced a dependency-safe guarded workflow.",
  )
  return plan.to_dict()


def default_agent_definitions() -> list[AgentDefinition]:
  return [*core_agent_definitions(), *specialist_agent_definitions()]


def core_agent_definitions() -> list[AgentDefinition]:
  return [
    core_agent("intent-analyzer-agent", "Intent Analyzer Agent", "Classify the user request and branch.", ["intent_analysis"]),
    core_agent("requirement-analyst-agent", "Requirement Analyst Agent", "Extract requirements, constraints, and missing information.", ["requirement_analysis"]),
    core_agent("task-decomposer-agent", "Task Decomposer Agent", "Break requirements into capability tasks.", ["task_decomposition"]),
    core_agent("agent-registry-agent", "Agent Registry Agent", "Match, create, and register capability agents.", ["agent_registry"]),
    core_agent("workflow-planner-agent", "Workflow Planner Agent", "Build dependency-aware execution plans.", ["workflow_planning"]),
    core_agent("supervisor-agent", "Supervisor Agent", "Select legal actions and enforce completion proof.", ["supervision"]),
    core_agent("memory-agent", "Memory Agent", "Load and persist project memory.", ["memory_persist"]),
  ]


def specialist_agent_definitions() -> list[AgentDefinition]:
  return [
    specialist_agent("domain-research-agent", "Domain Research Agent", "Research domain conventions and content requirements.", ["domain_research"]),
    specialist_agent("ux-layout-agent", "UX/Layout Agent", "Plan user journey, layout, and accessibility.", ["layout_plan", "ux_review", "accessibility_review"]),
    specialist_agent("content-agent", "Content Agent", "Create realistic website content strategy.", ["content_strategy"]),
    specialist_agent("component-ui-agent", "Component/UI Agent", "Plan reusable UI components and interactions.", ["component_plan"]),
    specialist_agent("code-generator-agent", "Code Generator Agent", "Generate React/Vite website artifacts.", ["code_generation"]),
    specialist_agent("validation-agent", "Validation Agent", "Validate generated artifact contracts.", ["artifact_validation"]),
    specialist_agent("preview-qa-agent", "Preview QA Agent", "Build and inspect staged previews.", ["preview_build", "visual_qa"]),
    specialist_agent("repair-agent", "Repair Agent", "Repair failed generated artifacts.", ["repair_if_needed"]),
  ]


def core_agent(agent_id: str, name: str, role: str, capabilities: list[str]) -> AgentDefinition:
  return AgentDefinition(
    id=agent_id,
    name=name,
    role=role,
    capabilities=capabilities,
    system_prompt=agent_system_prompt(name, role, include_update=True),
    tools=[],
    supported_domains=["any"],
    constraints={"python_tool_execution_only": True, "direct_file_writes": False},
    metrics={"usage_count": 0, "success_rate": 1.0, "successful_runs": 0},
    lifecycle="core",
  )


def specialist_agent(agent_id: str, name: str, role: str, capabilities: list[str]) -> AgentDefinition:
  return AgentDefinition(
    id=agent_id,
    name=name,
    role=role,
    capabilities=capabilities,
    system_prompt=agent_system_prompt(name, role, include_update=True),
    tools=[],
    supported_domains=["any"],
    constraints={"python_tool_execution_only": True, "direct_file_writes": False},
    metrics={"usage_count": 0, "success_rate": 0.95, "successful_runs": 0},
    lifecycle="reusable",
  )


def decompose_capability_tasks(prompt: str, *, domain: str, scope: str) -> list[CapabilityTask]:
  tasks = [
    task("domain_research", "Domain research", "domain_research", [], "low", "RUN_PROMPT_ANALYST"),
    task("content_strategy", "Content strategy", "content_strategy", ["domain_research"], "low", "RUN_DYNAMIC_SPECIALISTS"),
    task("layout_plan", "Layout plan", "layout_plan", ["domain_research"], "low", "RUN_PLANNER"),
    task("component_plan", "Component plan", "component_plan", ["layout_plan", "content_strategy"], "low", "RUN_DYNAMIC_SPECIALISTS"),
  ]
  for capability in domain_specific_capabilities(prompt, domain=domain):
    tasks.append(
      task(
        capability,
        title_name(capability),
        capability,
        ["domain_research", "layout_plan"],
        "medium",
        "RUN_DYNAMIC_SPECIALISTS",
      )
    )
  tasks.extend(
    [
      task("ux_review", "UX review", "ux_review", ["layout_plan", "component_plan"], "medium", "RUN_UX_REVIEW_AGENT"),
      task("accessibility_review", "Accessibility review", "accessibility_review", ["layout_plan"], "medium", "RUN_ACCESSIBILITY_AGENT"),
      task("code_generation", "Code generation", "code_generation", ["content_strategy", "component_plan", "ux_review", "accessibility_review"], "high", "RUN_CODE_AGENT"),
      task("artifact_validation", "Artifact validation", "artifact_validation", ["code_generation"], "high", "VALIDATE_PROJECT_ARTIFACT"),
      task("preview_build", "Preview build", "preview_build", ["artifact_validation"], "high", "BUILD_STAGED_PROJECT_PREVIEW"),
      task("visual_qa", "Visual QA", "visual_qa", ["preview_build"], "high", "RUN_PREVIEW_VISUAL_QA"),
      task("repair_if_needed", "Repair if needed", "repair_if_needed", ["artifact_validation", "preview_build", "visual_qa"], "high", "RUN_REPAIR_AGENT", optional=True),
      task("memory_persist", "Memory persist", "memory_persist", ["visual_qa"], "medium", "PERSIST_PROJECT_MEMORY"),
    ]
  )
  return tasks


def request_model_task_decomposition(
  provider: Any | None,
  prompt: str,
  *,
  routing_result: dict[str, Any],
  brief: dict[str, Any],
) -> list[CapabilityTask]:
  if provider is None or not hasattr(provider, "generate_json"):
    return []
  try:
    response = provider.generate_json(
      build_task_decomposition_prompt(prompt, routing_result=routing_result, brief=brief),
      system_instruction=agent_system_prompt("Task Decomposer Agent", "Decompose only safe, capability-specific tasks.", include_update=True),
      trace_label="dynamic_task_decomposer",
    )
  except Exception:
    return []
  raw_tasks = response.get("tasks") if isinstance(response, dict) else None
  if not isinstance(raw_tasks, list):
    return []
  normalized: list[CapabilityTask] = []
  for index, raw_task in enumerate(raw_tasks[:14], start=1):
    if not isinstance(raw_task, dict):
      continue
    capability = slug(raw_task.get("required_capability") or raw_task.get("capability"))
    if not capability:
      continue
    runtime_action = safe_runtime_action(raw_task.get("runtime_action"), capability)
    normalized.append(
      CapabilityTask(
        id=slug(raw_task.get("id") or capability or f"task-{index}"),
        name=text_value(raw_task.get("name")) or title_name(capability),
        required_capability=capability,
        description=text_value(raw_task.get("description")) or f"Handle {capability}.",
        input_schema=object_value(raw_task.get("input_schema")),
        output_schema=object_value(raw_task.get("output_schema")),
        dependencies=[slug(item) for item in string_list(raw_task.get("dependencies")) if slug(item)],
        risk_level=text_value(raw_task.get("risk_level")) if text_value(raw_task.get("risk_level")) in {"low", "medium", "high"} else "medium",
        runtime_action=runtime_action,
        optional=bool(raw_task.get("optional")),
      )
    )
  return normalized


def request_model_workflow_plan(
  provider: Any | None,
  tasks: list[CapabilityTask],
  assignments: list[AgentAssignment],
) -> dict[str, Any]:
  if provider is None or not hasattr(provider, "generate_json"):
    return {}
  try:
    response = provider.generate_json(
      build_workflow_planning_prompt(
        [task_item.to_dict() for task_item in tasks],
        [assignment.to_dict() for assignment in assignments],
      ),
      system_instruction=agent_system_prompt("Workflow Planner Agent", "Plan dependency-safe parallel groups with validation gates.", include_update=True),
      trace_label="dynamic_workflow_planner",
    )
  except Exception:
    return {}
  return response if isinstance(response, dict) else {}


def agent_system_prompt(name: str, role: str, *, include_update: bool) -> str:
  return (
    f"You are the {name}. {role} Return structured JSON only. "
    "Do not request direct file writes, deletes, or unapproved large rewrites. "
    "Delegate implementation, validation, preview, QA, commit, and memory persistence to Python runtime gates.\n"
    f"{prompt_policy_block(include_generation=True, include_update=include_update)}"
  )


def merge_capability_tasks(
  deterministic: list[CapabilityTask],
  model_tasks: list[CapabilityTask],
  *,
  domain: str,
) -> list[CapabilityTask]:
  merged = {task.id: task for task in deterministic}
  required_ids = set(merged)
  seen_capabilities = {task.required_capability for task in deterministic}
  added_model_dynamic_tasks = 0
  for task_item in model_tasks:
    if task_item.id in merged:
      continue
    if should_skip_model_capability_task(task_item, seen_capabilities=seen_capabilities):
      continue
    if len(merged) >= 18:
      break
    if task_item.runtime_action == "RUN_DYNAMIC_SPECIALISTS":
      if added_model_dynamic_tasks >= MODEL_DYNAMIC_TASK_LIMIT:
        continue
      added_model_dynamic_tasks += 1
    task_item.dependencies = [dependency for dependency in task_item.dependencies if dependency in required_ids or dependency in merged]
    merged[task_item.id] = task_item
    seen_capabilities.add(task_item.required_capability)
  return list(merged.values())


def should_skip_model_capability_task(
  task_item: CapabilityTask,
  *,
  seen_capabilities: set[str],
) -> bool:
  capability = task_item.required_capability
  if not capability:
    return True
  if capability in seen_capabilities:
    return True
  if task_item.runtime_action != "RUN_DYNAMIC_SPECIALISTS":
    return True
  if is_non_creatable_agent_capability(capability):
    return True
  if capability in {"file_write", "direct_file_write", "filesystem_write"}:
    return True
  return False


def build_parallel_groups(tasks: list[CapabilityTask]) -> list[list[str]]:
  task_by_id = {task_item.id: task_item for task_item in tasks}
  ordered_ids = [task_item.id for task_item in tasks]
  pending = set(ordered_ids)
  completed: set[str] = set()
  groups: list[list[str]] = []
  serial_actions = {
    "RUN_CODE_AGENT",
    "VALIDATE_PROJECT_ARTIFACT",
    "BUILD_STAGED_PROJECT_PREVIEW",
    "RUN_PREVIEW_VISUAL_QA",
    "RUN_REPAIR_AGENT",
    "PERSIST_PROJECT_MEMORY",
  }
  while pending:
    ready = [
      task_id
      for task_id in ordered_ids
      if task_id in pending and set(task_by_id[task_id].dependencies).issubset(completed)
    ]
    if not ready:
      groups.extend([[task_id] for task_id in ordered_ids if task_id in pending])
      break
    serial_ready = [task_id for task_id in ready if task_by_id[task_id].runtime_action in serial_actions]
    group = [serial_ready[0]] if serial_ready else ready
    groups.append(group)
    pending.difference_update(group)
    completed.update(group)
  return groups


def validate_parallel_groups(raw_groups: Any, tasks: list[CapabilityTask]) -> list[list[str]]:
  if not isinstance(raw_groups, list):
    return []
  task_by_id = {task_item.id: task_item for task_item in tasks}
  expected_ids = set(task_by_id)
  groups: list[list[str]] = []
  seen: set[str] = set()
  for raw_group in raw_groups:
    if not isinstance(raw_group, list):
      return []
    group = [text_value(task_id) for task_id in raw_group if text_value(task_id)]
    if not group or any(task_id not in expected_ids or task_id in seen for task_id in group):
      return []
    groups.append(group)
    seen.update(group)
  if seen != expected_ids:
    return []
  group_index = {task_id: index for index, group in enumerate(groups) for task_id in group}
  for task_item in tasks:
    if any(group_index.get(dependency, -1) >= group_index[task_item.id] for dependency in task_item.dependencies):
      return []
  guarded_actions = [
    "RUN_CODE_AGENT",
    "VALIDATE_PROJECT_ARTIFACT",
    "BUILD_STAGED_PROJECT_PREVIEW",
    "RUN_PREVIEW_VISUAL_QA",
    "PERSIST_PROJECT_MEMORY",
  ]
  guarded_positions = [
    min(group_index[task_item.id] for task_item in tasks if task_item.runtime_action == action)
    for action in guarded_actions
  ]
  if guarded_positions != sorted(guarded_positions) or len(set(guarded_positions)) != len(guarded_positions):
    return []
  return groups


def domain_specific_capabilities(prompt: str, *, domain: str) -> list[str]:
  _ = domain
  lowered = prompt.lower()
  capabilities: list[str] = []
  if any(term in lowered for term in ("payment", "checkout", "cart", "shop", "store")):
    capabilities.append("checkout_flow")
  if any(term in lowered for term in ("inventory", "catalog", "sku", "products", "product")):
    capabilities.append("inventory")
  if any(term in lowered for term in ("pipeline", "deal pipeline", "sales pipeline")):
    capabilities.append("crm_pipeline")
  if any(term in lowered for term in ("role", "permission", "rbac")):
    capabilities.append("rbac")
  if any(term in lowered for term in ("booking", "appointment", "reservation")):
    capabilities.append("booking_workflow")
  if any(term in lowered for term in ("analytics", "dashboard", "metrics", "kpi")):
    capabilities.append("analytics_dashboard")
  return capabilities[:MAX_DYNAMIC_AGENTS_PER_WORKFLOW]


def infer_dynamic_domain(prompt: str, brief: dict[str, Any]) -> str:
  _ = prompt
  business_type = slug(brief.get("business_type"))
  return business_type or "generic_website"


def infer_scope(prompt: str, brief: dict[str, Any]) -> str:
  text = f"{prompt}\n{json.dumps(brief, ensure_ascii=False)}".lower()
  structured_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", text))
  if structured_items >= 5 or len(text) > 1200:
    return "large"
  if structured_items >= 2 or len(text) > 400:
    return "medium"
  return "small"


def safe_runtime_action(value: Any, capability: str) -> str:
  allowed = {
    "RUN_PROMPT_ANALYST",
    "RUN_PLANNER",
    "RUN_DYNAMIC_SPECIALISTS",
    "RUN_UX_REVIEW_AGENT",
    "RUN_ACCESSIBILITY_AGENT",
    "RUN_CODE_AGENT",
    "VALIDATE_PROJECT_ARTIFACT",
    "BUILD_STAGED_PROJECT_PREVIEW",
    "RUN_PREVIEW_VISUAL_QA",
    "RUN_REPAIR_AGENT",
    "PERSIST_PROJECT_MEMORY",
  }
  selected = text_value(value)
  if selected in allowed:
    return selected
  mapping = {
    "domain_research": "RUN_PROMPT_ANALYST",
    "layout_plan": "RUN_PLANNER",
    "code_generation": "RUN_CODE_AGENT",
    "artifact_validation": "VALIDATE_PROJECT_ARTIFACT",
    "preview_build": "BUILD_STAGED_PROJECT_PREVIEW",
    "visual_qa": "RUN_PREVIEW_VISUAL_QA",
    "repair_if_needed": "RUN_REPAIR_AGENT",
    "memory_persist": "PERSIST_PROJECT_MEMORY",
  }
  return mapping.get(capability, "RUN_DYNAMIC_SPECIALISTS")


def task(
  task_id: str,
  name: str,
  capability: str,
  dependencies: list[str],
  risk_level: str,
  runtime_action: str,
  *,
  optional: bool = False,
) -> CapabilityTask:
  return CapabilityTask(
    id=task_id,
    name=name,
    required_capability=capability,
    description=f"Complete the {name.lower()} capability for the website workflow.",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    dependencies=dependencies,
    risk_level=risk_level,
    runtime_action=runtime_action,
    optional=optional,
  )

