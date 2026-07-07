from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


MAS_RUNTIME_NAME = "worktual-mas-runtime"
AGENT_CONTRACT_SCHEMA_VERSION = "worktual-mas-contract-v1"


class MASContractError(RuntimeError):
  pass


def utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentContract:
  id: str
  name: str
  role: str
  responsibility: str
  allowed_actions: tuple[str, ...]
  allowed_tools: tuple[str, ...] = ()
  goal: str = ""
  input_schema: dict[str, Any] = field(default_factory=dict)
  output_schema: dict[str, Any] = field(default_factory=dict)
  timeout_seconds: int = 120
  max_retries: int = 0
  backend_authority: bool = False
  requires_completion_gate: bool = False

  def to_dict(self) -> dict[str, Any]:
    payload = asdict(self)
    payload["schema_version"] = AGENT_CONTRACT_SCHEMA_VERSION
    payload["allowed_actions"] = list(self.allowed_actions)
    payload["allowed_tools"] = list(self.allowed_tools)
    return payload


@dataclass
class AgentInput:
  action: str
  prompt: str
  project_id: str
  routing_intent: str
  decision: dict[str, Any] = field(default_factory=dict)
  context_refs: dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class AgentOutput:
  step_id: str
  contract_id: str
  agent: str
  action: str
  status: str
  input: dict[str, Any]
  output: dict[str, Any]
  tool_calls: list[dict[str, Any]]
  started_at: str
  completed_at: str
  duration_ms: int
  error: str = ""

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class AgentHandoff:
  handoff_id: str
  sequence: int
  from_agent: str
  to_agent: str
  from_action: str
  to_action: str
  status: str
  input: dict[str, Any]
  output: dict[str, Any]
  requested_tool_calls: list[Any] = field(default_factory=list)
  contract_id: str = ""
  created_at: str = field(default_factory=utc_now_iso)
  source: str = "real_mas_runtime"

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


@dataclass
class MASRunState:
  runtime: str
  project_id: str
  prompt: str
  routing_result: dict[str, Any]
  status: str = "running"
  schema_version: str = AGENT_CONTRACT_SCHEMA_VERSION
  steps: list[dict[str, Any]] = field(default_factory=list)
  handoffs: list[dict[str, Any]] = field(default_factory=list)
  contracts: list[dict[str, Any]] = field(default_factory=list)
  guardrails: dict[str, Any] = field(default_factory=dict)
  started_at: str = field(default_factory=utc_now_iso)
  completed_at: str = ""

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)
