from __future__ import annotations

from typing import Any

from .constants import ALLOWED_DYNAMIC_TOOLS, FORBIDDEN_DYNAMIC_TOOLS, NON_CREATABLE_AGENT_CAPABILITIES, PROJECT_SPECIFIC_AGENT_PROMPT_PATTERNS
from .models import AgentDefinition, CapabilityTask
from .prompts import generic_dynamic_agent_prompt
from .utils import object_value, slug, text_value


def is_non_creatable_agent_capability(capability: Any) -> bool:
  return slug(capability) in NON_CREATABLE_AGENT_CAPABILITIES


def should_create_dynamic_agent_for_task(task: CapabilityTask) -> tuple[bool, str]:
  if task.runtime_action != "RUN_DYNAMIC_SPECIALISTS":
    return (
      False,
      f"{task.runtime_action} is a Python-guarded runtime action and cannot create a reusable dynamic agent.",
    )
  if is_non_creatable_agent_capability(task.required_capability):
    return (
      False,
      f"{task.required_capability} is a core/specialist capability and cannot be created as a user dynamic agent.",
    )
  return True, ""


def is_project_specific_agent_prompt(system_prompt: Any) -> bool:
  prompt = text_value(system_prompt)
  return bool(prompt and any(pattern.search(prompt) for pattern in PROJECT_SPECIFIC_AGENT_PROMPT_PATTERNS))


def dynamic_agent_definition_rejection_reasons(definition: AgentDefinition) -> list[str]:
  reasons: list[str] = []
  non_creatable_capabilities = [
    capability for capability in definition.capabilities if is_non_creatable_agent_capability(capability)
  ]
  if non_creatable_capabilities:
    reasons.append(
      "non_creatable_capabilities:" + ",".join(sorted(set(non_creatable_capabilities)))
    )
  declared_tools = set(definition.allowed_tools or definition.tools)
  forbidden_tools = sorted(declared_tools.intersection(FORBIDDEN_DYNAMIC_TOOLS))
  unknown_tools = sorted(tool for tool in declared_tools if tool not in ALLOWED_DYNAMIC_TOOLS)
  if forbidden_tools:
    reasons.append("forbidden_tools:" + ",".join(forbidden_tools))
  if unknown_tools:
    reasons.append("unknown_tools:" + ",".join(unknown_tools))
  constraints = object_value(definition.constraints)
  if constraints.get("direct_file_writes") is True:
    reasons.append("direct_file_writes_enabled")
  if constraints.get("python_tool_execution_only") is False:
    reasons.append("python_tool_execution_only_disabled")
  if is_project_specific_agent_prompt(definition.system_prompt):
    reasons.append("project_specific_system_prompt")
  return reasons


def persistable_agent_definition_payload(definition: AgentDefinition) -> dict[str, Any]:
  payload = definition.to_dict()
  payload.pop("metrics", None)
  payload["tools"] = [tool for tool in definition.tools if tool in ALLOWED_DYNAMIC_TOOLS]
  payload["allowed_tools"] = [tool for tool in definition.allowed_tools if tool in ALLOWED_DYNAMIC_TOOLS]
  return payload
