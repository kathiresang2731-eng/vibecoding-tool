from __future__ import annotations

from typing import Any

from ..agent_tool_catalog import RUNTIME_AGENT_POLICIES
from ..runtime_agents.registry import ACTION_REGISTRY, RUNTIME_AGENT_GROUPS
from .contracts import AgentContract


COMMIT_GATE_ACTIONS = (
  "VALIDATE_PROJECT_ARTIFACT",
  "BUILD_STAGED_PROJECT_PREVIEW",
  "RUN_PREVIEW_VISUAL_QA",
)


def _schema(required: list[str] | None = None) -> dict[str, Any]:
  return {
    "type": "object",
    "required": list(required or []),
    "additionalProperties": True,
  }


def normalize_contract_id(value: str) -> str:
  normalized = "".join(character.lower() if character.isalnum() else "-" for character in str(value or "agent"))
  while "--" in normalized:
    normalized = normalized.replace("--", "-")
  return normalized.strip("-") or "runtime-agent"


def _allowed_tools(actions: tuple[str, ...]) -> tuple[str, ...]:
  tools: list[str] = []
  for action in actions:
    for tool in ACTION_REGISTRY[action].get("tools", []):
      if tool not in tools:
        tools.append(tool)
  return tuple(tools)


def _build_runtime_contract(agent_name: str) -> AgentContract:
  policy = RUNTIME_AGENT_POLICIES[agent_name]
  actions = tuple(RUNTIME_AGENT_GROUPS[agent_name])
  declared_tools = tuple(policy.get("tools") or _allowed_tools(actions))
  return AgentContract(
    id=normalize_contract_id(agent_name),
    name=agent_name,
    role=str(policy["role"]),
    responsibility=str(policy["responsibility"]),
    allowed_actions=actions,
    allowed_tools=declared_tools,
    goal=str(policy.get("goal") or ""),
    input_schema=_schema(list(policy.get("input") or [])),
    output_schema=_schema(list(policy.get("output") or [])),
    max_retries=int(policy.get("max_retries") or 0),
    backend_authority=bool(policy.get("backend_authority")),
    requires_completion_gate=bool(policy.get("requires_completion_gate")),
  )


RUNTIME_AGENT_CONTRACTS: tuple[AgentContract, ...] = tuple(
  _build_runtime_contract(agent_name)
  for agent_name in RUNTIME_AGENT_GROUPS
  if agent_name != "Supervisor Agent"
)


def ordered_runtime_agent_contracts() -> list[dict[str, Any]]:
  return [contract.to_dict() for contract in RUNTIME_AGENT_CONTRACTS]


def agent_contract_for_action(action: str, *, agent_name: str | None = None) -> AgentContract:
  for contract in RUNTIME_AGENT_CONTRACTS:
    if action in contract.allowed_actions:
      return contract
  return AgentContract(
    id=normalize_contract_id(agent_name or action or "runtime-agent"),
    name=agent_name or "Runtime Agent",
    role="runtime_action",
    responsibility="Execute a backend-approved runtime action.",
    allowed_actions=(action,),
    goal="Complete the assigned runtime action safely.",
    input_schema=_schema(),
    output_schema=_schema(),
  )
