from __future__ import annotations

from typing import Any

from ..budget_config import AGENT_BUDGETS

from ..prompts import build_dynamic_agent_definition_prompt
try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block

try:
  from ...audit_logging import log_dynamic_agent_event
except ImportError:
  from audit_logging import log_dynamic_agent_event

from .config import (
  default_dynamic_metrics,
  dynamic_agent_max_patch_bytes,
  dynamic_agent_max_patch_files,
  dynamic_agent_max_tool_calls,
  dynamic_agent_promotion_min_successes,
  dynamic_agent_timeout_seconds,
)
from .constants import ALLOWED_DYNAMIC_TOOLS, MAX_DYNAMIC_AGENTS_PER_WORKFLOW, PYTHON_GUARDED_ACTION_OWNERS
from .models import AgentAssignment, AgentDefinition, CapabilityTask
from .policy import (
  dynamic_agent_definition_rejection_reasons,
  generic_dynamic_agent_prompt,
  is_non_creatable_agent_capability,
  is_project_specific_agent_prompt,
  should_create_dynamic_agent_for_task,
)
from .utils import object_value, slug, string_list, text_value, title_name, unique_strings


class AgentRegistry:
  def __init__(
    self,
    definitions: list[AgentDefinition] | None = None,
    *,
    owner_user_id: str | None = None,
  ) -> None:
    self.owner_user_id = owner_user_id
    self.agents: dict[str, AgentDefinition] = {}
    self.capability_index: dict[str, list[str]] = {}
    for definition in definitions or default_agent_definitions():
      self.register(definition)

  def register(self, definition: AgentDefinition) -> AgentDefinition:
    declared_tools = definition.allowed_tools or definition.tools
    definition.allowed_tools = [tool for tool in declared_tools if tool in ALLOWED_DYNAMIC_TOOLS]
    definition.tools = list(definition.allowed_tools)
    self.agents[definition.id] = definition
    for capability in definition.capabilities:
      agent_ids = self.capability_index.setdefault(capability, [])
      if definition.id not in agent_ids:
        agent_ids.append(definition.id)
    return definition

  def find_agents_by_capability(self, capability: str) -> list[AgentDefinition]:
    return [self.agents[agent_id] for agent_id in self.capability_index.get(capability, []) if agent_id in self.agents]

  def find_best_agent(self, task: CapabilityTask, *, domain: str) -> tuple[AgentDefinition | None, float]:
    candidates = self.find_agents_by_capability(task.required_capability)
    scored = [(candidate, self.score_agent(candidate, task, domain=domain)) for candidate in candidates]
    scored = [(candidate, score) for candidate, score in scored if score > 0]
    if not scored:
      return None, 0.0
    return max(scored, key=lambda item: item[1])

  def score_agent(self, agent: AgentDefinition, task: CapabilityTask, *, domain: str) -> float:
    if agent.lifecycle == "disabled":
      return 0.0
    if task.required_capability not in agent.capabilities:
      return 0.0
    supported_domains = {item.lower() for item in agent.supported_domains}
    domain_score = 1.0 if "any" in supported_domains or domain.lower() in supported_domains else 0.0
    if domain_score == 0:
      return 0.0
    success_rate = float(agent.metrics.get("success_rate") or 0.9)
    usage_count = min(int(agent.metrics.get("usage_count") or 0), 100) / 100
    lifecycle_score = 1.0 if agent.lifecycle in {"core", "reusable"} else 0.65
    return round(0.45 + domain_score * 0.2 + success_rate * 0.2 + usage_count * 0.05 + lifecycle_score * 0.1, 4)

  def create_dynamic_agent(
    self,
    task: CapabilityTask,
    *,
    domain: str,
    provider: Any | None = None,
  ) -> AgentDefinition:
    allowed_to_create, rejection_reason = should_create_dynamic_agent_for_task(task)
    if not allowed_to_create:
      log_dynamic_agent_event(
        "agent.creation_rejected",
        status="rejected",
        payload={
          "owner_user_id": self.owner_user_id,
          "task_id": task.id,
          "required_capability": task.required_capability,
          "runtime_action": task.runtime_action,
          "reason": rejection_reason,
        },
      )
      raise ValueError(rejection_reason)
    generated: dict[str, Any] = {}
    if provider is not None and hasattr(provider, "generate_json"):
      try:
        response = provider.generate_json(
          build_dynamic_agent_definition_prompt(task.to_dict(), domain=domain),
          system_instruction=dynamic_agent_registry_system_prompt("dynamic agent factory"),
          trace_label=f"create_dynamic_agent_{task.required_capability}",
        )
        generated = response if isinstance(response, dict) else {}
      except Exception:
        generated = {}
    agent_id = slug(generated.get("id") or f"{task.required_capability}-agent")
    existing = self.agents.get(agent_id)
    if existing and existing.lifecycle != "disabled" and task.required_capability in existing.capabilities:
      if domain not in existing.supported_domains and "any" not in existing.supported_domains:
        existing.supported_domains.append(domain)
      return existing
    if existing:
      version_suffix = f"v{int(existing.version or 1) + 1}" if existing.lifecycle == "disabled" else domain
      agent_id = slug(f"{task.required_capability}-{version_suffix}-agent")
    name = text_value(generated.get("name")) or title_name(task.required_capability)
    system_prompt = text_value(generated.get("system_prompt")) or generic_dynamic_agent_prompt(
      name,
      task.required_capability,
      domain,
    )
    if is_project_specific_agent_prompt(system_prompt):
      log_dynamic_agent_event(
        "agent.definition_sanitized",
        payload={
          "owner_user_id": self.owner_user_id,
          "agent_id": agent_id,
          "task_id": task.id,
          "reason": "Model returned a project-specific dynamic agent prompt; Python replaced it with a reusable prompt.",
        },
      )
      system_prompt = generic_dynamic_agent_prompt(name, task.required_capability, domain)
    capabilities = [
      capability
      for capability in unique_strings([slug(item) for item in string_list(generated.get("capabilities")) if slug(item)])
      if not is_non_creatable_agent_capability(capability)
    ] or [task.required_capability]
    if task.required_capability not in capabilities:
      capabilities.insert(0, task.required_capability)
    supported_domains = string_list(generated.get("supported_domains")) or [domain]
    definition = AgentDefinition(
      id=agent_id,
      name=name,
      role=text_value(generated.get("role")) or task.description,
      capabilities=capabilities[:6],
      system_prompt=system_prompt,
      tools=list(ALLOWED_DYNAMIC_TOOLS),
      supported_domains=supported_domains[:6],
      constraints={
        "max_tokens": AGENT_BUDGETS.specialist_output_tokens,
        "temperature": 0.2,
        "python_tool_execution_only": True,
        "direct_file_writes": False,
      },
      metrics=default_dynamic_metrics(),
      lifecycle="experimental",
      owner_user_id=self.owner_user_id,
      allowed_tools=list(ALLOWED_DYNAMIC_TOOLS),
      input_schema=object_value(task.input_schema) or {"type": "object"},
      output_schema=object_value(task.output_schema) or {"type": "object"},
      execution_phase="implementation",
      timeout_seconds=dynamic_agent_timeout_seconds(),
      tool_call_budget=dynamic_agent_max_tool_calls(),
      candidate_change_limits={
        "max_files": dynamic_agent_max_patch_files(),
        "max_bytes_per_file": dynamic_agent_max_patch_bytes(),
      },
    )
    rejection_reasons = dynamic_agent_definition_rejection_reasons(definition)
    if rejection_reasons:
      log_dynamic_agent_event(
        "agent.creation_rejected",
        status="rejected",
        payload={
          "owner_user_id": self.owner_user_id,
          "agent_id": definition.id,
          "task_id": task.id,
          "required_capability": task.required_capability,
          "reasons": rejection_reasons,
        },
      )
      raise ValueError("Dynamic agent definition rejected: " + "; ".join(rejection_reasons))
    registered = self.register(definition)
    log_dynamic_agent_event(
      "agent.created",
      payload={
        "agent_id": registered.id,
        "owner_user_id": registered.owner_user_id,
        "capabilities": registered.capabilities,
        "supported_domains": registered.supported_domains,
        "lifecycle": registered.lifecycle,
        "allowed_tools": registered.allowed_tools,
      },
    )
    return registered

  def assign_tasks(
    self,
    tasks: list[CapabilityTask],
    *,
    domain: str,
    provider: Any | None = None,
    max_dynamic_agents: int = MAX_DYNAMIC_AGENTS_PER_WORKFLOW,
  ) -> tuple[list[AgentAssignment], list[str], list[str]]:
    assignments: list[AgentAssignment] = []
    created_ids: list[str] = []
    reused_ids: list[str] = []
    fallback = self.agents["task-decomposer-agent"]
    for task in tasks:
      agent, score = self.find_best_agent(task, domain=domain)
      log_dynamic_agent_event(
        "registry.lookup",
        payload={
          "owner_user_id": self.owner_user_id,
          "task_id": task.id,
          "required_capability": task.required_capability,
          "domain": domain,
          "matched_agent_id": agent.id if agent else None,
          "confidence": round(score, 4),
        },
      )
      assignment_type = "reused"
      reason = f"Registry matched capability {task.required_capability}."
      can_create, create_rejection_reason = should_create_dynamic_agent_for_task(task)
      if agent is None and can_create and len(created_ids) < max_dynamic_agents:
        agent = self.create_dynamic_agent(task, domain=domain, provider=provider)
        score = 0.72
        assignment_type = "created"
        reason = f"No reusable agent covered {task.required_capability}; created an experimental specialist."
        if agent.id not in created_ids:
          created_ids.append(agent.id)
      elif agent is None:
        fallback_agent_id = PYTHON_GUARDED_ACTION_OWNERS.get(task.runtime_action, fallback.id)
        agent = self.agents.get(fallback_agent_id) or fallback
        score = 0.45
        assignment_type = "fallback"
        reason = (
          create_rejection_reason
          or f"Dynamic agent limit reached; assigned guarded fallback for {task.required_capability}."
        )
      elif agent.id not in reused_ids:
        reused_ids.append(agent.id)
      assignments.append(
        AgentAssignment(
          task_id=task.id,
          agent_id=agent.id,
          agent_name=agent.name,
          capability=task.required_capability,
          assignment_type=assignment_type,
          confidence=round(score, 3),
          reason=reason,
        )
      )
      log_dynamic_agent_event(
        "agent.assigned",
        payload={
          "owner_user_id": self.owner_user_id,
          "task_id": task.id,
          "agent_id": agent.id,
          "assignment_type": assignment_type,
          "confidence": round(score, 3),
          "reason": reason,
        },
      )
    return assignments, created_ids, reused_ids

  def mark_workflow_success(self, assignments: list[dict[str, Any]] | list[AgentAssignment]) -> None:
    recorded_agent_ids: set[str] = set()
    for assignment in assignments:
      agent_id = assignment.agent_id if isinstance(assignment, AgentAssignment) else text_value(assignment.get("agent_id"))
      agent = self.agents.get(agent_id)
      if not agent or agent_id in recorded_agent_ids:
        continue
      recorded_agent_ids.add(agent_id)
      successful_runs = int(agent.metrics.get("successful_runs") or 0) + 1
      usage_count = int(agent.metrics.get("usage_count") or 0) + 1
      agent.metrics["successful_runs"] = successful_runs
      agent.metrics["usage_count"] = usage_count
      agent.metrics["success_rate"] = round(successful_runs / usage_count, 4)
      agent.metrics["consecutive_failures"] = 0
      if (
        agent.lifecycle == "experimental"
        and successful_runs >= dynamic_agent_promotion_min_successes()
        and agent.metrics["success_rate"] >= 0.8
        and int(agent.metrics.get("safety_violations") or 0) == 0
      ):
        agent.lifecycle = "reusable"
        log_dynamic_agent_event(
          "agent.promoted",
          payload={"agent_id": agent.id, "lifecycle": agent.lifecycle, "metrics": agent.metrics},
        )
      else:
        log_dynamic_agent_event(
          "agent.evaluated",
          payload={"agent_id": agent.id, "lifecycle": agent.lifecycle, "metrics": agent.metrics},
        )

  def mark_workflow_failure(
    self,
    assignments: list[dict[str, Any]] | list[AgentAssignment],
    *,
    reason: str,
    safety_violation: bool = False,
  ) -> None:
    recorded_agent_ids: set[str] = set()
    for assignment in assignments:
      agent_id = assignment.agent_id if isinstance(assignment, AgentAssignment) else text_value(assignment.get("agent_id"))
      agent = self.agents.get(agent_id)
      if not agent or agent_id in recorded_agent_ids or agent.lifecycle == "core":
        continue
      recorded_agent_ids.add(agent_id)
      usage_count = int(agent.metrics.get("usage_count") or 0) + 1
      failed_runs = int(agent.metrics.get("failed_runs") or 0) + 1
      consecutive_failures = int(agent.metrics.get("consecutive_failures") or 0) + 1
      successful_runs = int(agent.metrics.get("successful_runs") or 0)
      agent.metrics.update(
        {
          "usage_count": usage_count,
          "failed_runs": failed_runs,
          "consecutive_failures": consecutive_failures,
          "success_rate": round(successful_runs / usage_count, 4),
          "last_failure_reason": reason[:600],
        }
      )
      if safety_violation:
        agent.metrics["safety_violations"] = int(agent.metrics.get("safety_violations") or 0) + 1
      if consecutive_failures >= 3:
        agent.lifecycle = "disabled"
        agent.metrics["disabled_reason"] = reason[:600]
        log_dynamic_agent_event(
          "agent.disabled",
          status="failed",
          payload={"agent_id": agent.id, "reason": reason, "metrics": agent.metrics},
        )
      else:
        log_dynamic_agent_event(
          "agent.execution_failed",
          status="failed",
          payload={"agent_id": agent.id, "reason": reason, "metrics": agent.metrics},
        )

  def snapshot(self, *, agent_ids: list[str] | None = None) -> dict[str, Any]:
    selected = self.agents.values() if not agent_ids else [self.agents[agent_id] for agent_id in agent_ids if agent_id in self.agents]
    agents = [definition.to_dict() for definition in selected]
    return {
      "agent_count": len(agents),
      "core_count": sum(1 for item in agents if item["lifecycle"] == "core"),
      "reusable_count": sum(1 for item in agents if item["lifecycle"] == "reusable"),
      "experimental_count": sum(1 for item in agents if item["lifecycle"] == "experimental"),
      "agents": agents,
    }


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
    system_prompt=dynamic_agent_registry_system_prompt(name, role),
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
    system_prompt=dynamic_agent_registry_system_prompt(name, role),
    tools=[],
    supported_domains=["any"],
    constraints={"python_tool_execution_only": True, "direct_file_writes": False},
    metrics={"usage_count": 0, "success_rate": 0.95, "successful_runs": 0},
    lifecycle="reusable",
  )


def dynamic_agent_registry_system_prompt(name: str, role: str = "") -> str:
  role_text = f" {role}" if role else ""
  return (
    f"You are the {name}.{role_text} Return structured JSON only. "
    "Create reusable, domain-safe agent definitions only. Do not hard-code user "
    "identity, current project names, file paths, brand palettes, or one-off prompts. "
    "Do not request deletes, direct file writes, unapproved tools, or large rewrites.\n"
    f"{prompt_policy_block(include_generation=True, include_update=True)}"
  )
