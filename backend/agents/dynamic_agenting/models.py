from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentDefinition:
  id: str
  name: str
  role: str
  capabilities: list[str]
  system_prompt: str
  tools: list[str]
  supported_domains: list[str]
  constraints: dict[str, Any]
  metrics: dict[str, Any]
  lifecycle: str = "reusable"
  version: int = 1
  owner_user_id: str | None = None
  allowed_tools: list[str] = field(default_factory=list)
  input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
  output_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})
  execution_phase: str = "planning"
  timeout_seconds: int = 60
  tool_call_budget: int = 6
  candidate_change_limits: dict[str, int] = field(
    default_factory=lambda: {"max_files": 6, "max_bytes_per_file": 262144}
  )

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class CapabilityTask:
  id: str
  name: str
  required_capability: str
  description: str
  input_schema: dict[str, Any]
  output_schema: dict[str, Any]
  dependencies: list[str]
  risk_level: str
  runtime_action: str
  optional: bool = False

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class AgentAssignment:
  task_id: str
  agent_id: str
  agent_name: str
  capability: str
  assignment_type: str
  confidence: float
  reason: str

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class WorkflowPlan:
  domain: str
  scope: str
  tasks: list[CapabilityTask]
  assignments: list[AgentAssignment]
  dependency_graph: dict[str, list[str]]
  parallel_groups: list[list[str]]
  completion_proof: list[str]
  active_agents: list[dict[str, Any]]
  created_agent_ids: list[str] = field(default_factory=list)
  reused_agent_ids: list[str] = field(default_factory=list)
  planning_source: str = "python_guardrail"
  planner_reason: str = ""

  def to_dict(self) -> dict[str, Any]:
    return {
      "domain": self.domain,
      "scope": self.scope,
      "tasks": [task.to_dict() for task in self.tasks],
      "assignments": [assignment.to_dict() for assignment in self.assignments],
      "dependency_graph": self.dependency_graph,
      "parallel_groups": self.parallel_groups,
      "completion_proof": self.completion_proof,
      "active_agents": self.active_agents,
      "created_agent_ids": self.created_agent_ids,
      "reused_agent_ids": self.reused_agent_ids,
      "planning_source": self.planning_source,
      "planner_reason": self.planner_reason,
    }
