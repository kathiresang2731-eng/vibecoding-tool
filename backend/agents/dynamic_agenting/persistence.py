from __future__ import annotations

import json
from typing import Any

from ..budget_config import AGENT_BUDGETS

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
from .constants import ALLOWED_DYNAMIC_TOOLS
from .models import AgentDefinition
from .policy import (
  dynamic_agent_definition_rejection_reasons,
  is_non_creatable_agent_capability,
  is_project_specific_agent_prompt,
  persistable_agent_definition_payload,
)
from .registry import AgentRegistry
from .utils import list_value, object_value, slug, string_list, text_value, title_name, unique_strings


def runtime_agent_name_for_action(workflow_plan: dict[str, Any], action: str, fallback: str) -> str:
  assignments = {
    text_value(item.get("task_id")): item
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  }
  for task_item in list_value(workflow_plan.get("tasks")):
    if not isinstance(task_item, dict) or task_item.get("runtime_action") != action:
      continue
    assignment = assignments.get(text_value(task_item.get("id")))
    if isinstance(assignment, dict) and text_value(assignment.get("agent_name")):
      return text_value(assignment.get("agent_name"))
  return fallback


def build_user_agent_registry(store: Any, user: Any) -> AgentRegistry:
  owner_user_id = text_value(getattr(user, "id", None))
  registry = AgentRegistry(owner_user_id=owner_user_id or None)
  if store is None or not hasattr(store, "list_dynamic_agent_definitions"):
    log_dynamic_agent_event(
      "registry.hydrated",
      status="skipped",
      payload={"owner_user_id": owner_user_id, "reason": "Dynamic agent persistence is unavailable."},
    )
    return registry
  try:
    rows = store.list_dynamic_agent_definitions(user, include_disabled=True)
  except Exception as exc:
    log_dynamic_agent_event(
      "registry.hydration_failed",
      status="failed",
      payload={"owner_user_id": owner_user_id, "error": str(exc)},
    )
    return registry
  hydrated_ids: list[str] = []
  for row in list_value(rows):
    definition = agent_definition_from_storage_row(row, owner_user_id=owner_user_id)
    if definition is None or definition.id in registry.agents:
      continue
    registry.register(definition)
    hydrated_ids.append(definition.id)
  log_dynamic_agent_event(
    "registry.hydrated",
    payload={"owner_user_id": owner_user_id, "agent_ids": hydrated_ids, "agent_count": len(hydrated_ids)},
  )
  return registry


def persist_user_dynamic_agents(
  store: Any,
  user: Any,
  registry: AgentRegistry,
  *,
  agent_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
  if store is None or not hasattr(store, "upsert_dynamic_agent_definition"):
    return []
  selected_ids = set(agent_ids or list(registry.agents.keys()))
  persisted: list[dict[str, Any]] = []
  for agent_id in selected_ids:
    definition = registry.agents.get(agent_id)
    if definition is None or not definition.owner_user_id:
      continue
    rejection_reasons = dynamic_agent_definition_rejection_reasons(definition)
    if rejection_reasons:
      log_dynamic_agent_event(
        "agent.persistence_rejected",
        status="rejected",
        payload={
          "agent_id": definition.id,
          "owner_user_id": definition.owner_user_id,
          "reasons": rejection_reasons,
        },
      )
      continue
    try:
      row = store.upsert_dynamic_agent_definition(
        user,
        agent_key=definition.id,
        lifecycle=definition.lifecycle,
        definition=persistable_agent_definition_payload(definition),
        metrics=definition.metrics,
      )
      if isinstance(row, dict):
        definition.version = int(row.get("version") or definition.version)
        persisted.append(row)
      log_dynamic_agent_event(
        "agent.persisted",
        payload={
          "agent_id": definition.id,
          "owner_user_id": definition.owner_user_id,
          "version": definition.version,
          "lifecycle": definition.lifecycle,
        },
      )
    except Exception as exc:
      log_dynamic_agent_event(
        "agent.persistence_failed",
        status="failed",
        payload={"agent_id": definition.id, "owner_user_id": definition.owner_user_id, "error": str(exc)},
      )
  return persisted


def agent_definition_from_storage_row(
  row: Any,
  *,
  owner_user_id: str,
) -> AgentDefinition | None:
  if not isinstance(row, dict):
    return None
  raw_definition = row.get("definition_json")
  if isinstance(raw_definition, str):
    try:
      raw_definition = json.loads(raw_definition)
    except json.JSONDecodeError:
      raw_definition = {}
  definition = object_value(raw_definition)
  agent_id = slug(row.get("agent_key") or definition.get("id"))
  capabilities = unique_strings([slug(item) for item in string_list(definition.get("capabilities")) if slug(item)])
  if not agent_id or not capabilities:
    return None
  if any(is_non_creatable_agent_capability(capability) for capability in capabilities):
    log_dynamic_agent_event(
      "agent.hydration_rejected",
      status="rejected",
      payload={
        "owner_user_id": owner_user_id,
        "agent_id": agent_id,
        "reasons": [
          "non_creatable_capabilities:"
          + ",".join(sorted(capability for capability in capabilities if is_non_creatable_agent_capability(capability)))
        ],
      },
    )
    return None
  raw_constraints = object_value(definition.get("constraints"))
  if raw_constraints.get("direct_file_writes") is True or raw_constraints.get("python_tool_execution_only") is False:
    reasons = []
    if raw_constraints.get("direct_file_writes") is True:
      reasons.append("direct_file_writes_enabled")
    if raw_constraints.get("python_tool_execution_only") is False:
      reasons.append("python_tool_execution_only_disabled")
    log_dynamic_agent_event(
      "agent.hydration_rejected",
      status="rejected",
      payload={"owner_user_id": owner_user_id, "agent_id": agent_id, "reasons": reasons},
    )
    return None
  if is_project_specific_agent_prompt(definition.get("system_prompt")):
    log_dynamic_agent_event(
      "agent.hydration_rejected",
      status="rejected",
      payload={
        "owner_user_id": owner_user_id,
        "agent_id": agent_id,
        "reasons": ["project_specific_system_prompt"],
      },
    )
    return None
  raw_metrics = row.get("metrics_json")
  if isinstance(raw_metrics, str):
    try:
      raw_metrics = json.loads(raw_metrics)
    except json.JSONDecodeError:
      raw_metrics = {}
  metrics = {**default_dynamic_metrics(), **object_value(definition.get("metrics")), **object_value(raw_metrics)}
  allowed_tools = [
    tool
    for tool in unique_strings(string_list(definition.get("allowed_tools") or definition.get("tools")))
    if tool in ALLOWED_DYNAMIC_TOOLS
  ]
  lifecycle = text_value(row.get("lifecycle") or definition.get("lifecycle")) or "experimental"
  if lifecycle not in {"experimental", "reusable", "disabled"}:
    lifecycle = "experimental"
  restored = AgentDefinition(
    id=agent_id,
    name=text_value(definition.get("name")) or title_name(agent_id),
    role=text_value(definition.get("role")) or f"Provide {capabilities[0]} recommendations.",
    capabilities=capabilities[:6],
    system_prompt=text_value(definition.get("system_prompt")) or (
      f"You are the {title_name(agent_id)}. Return structured recommendations only."
    ),
    tools=allowed_tools,
    supported_domains=unique_strings(
      [slug(item) for item in string_list(definition.get("supported_domains")) if slug(item)]
    )[:6] or ["any"],
    constraints={
      **object_value(definition.get("constraints")),
      "python_tool_execution_only": True,
      "direct_file_writes": False,
    },
    metrics=metrics,
    lifecycle=lifecycle,
    version=int(row.get("version") or definition.get("version") or 1),
    owner_user_id=owner_user_id,
    allowed_tools=allowed_tools,
    input_schema=object_value(definition.get("input_schema")) or {"type": "object"},
    output_schema=object_value(definition.get("output_schema")) or {"type": "object"},
    execution_phase=text_value(definition.get("execution_phase")) or "planning",
    timeout_seconds=dynamic_agent_timeout_seconds(),
    tool_call_budget=dynamic_agent_max_tool_calls(),
    candidate_change_limits={
      "max_files": dynamic_agent_max_patch_files(),
      "max_bytes_per_file": dynamic_agent_max_patch_bytes(),
    },
  )
  rejection_reasons = dynamic_agent_definition_rejection_reasons(restored)
  if rejection_reasons:
    log_dynamic_agent_event(
      "agent.hydration_rejected",
      status="rejected",
      payload={"owner_user_id": owner_user_id, "agent_id": agent_id, "reasons": rejection_reasons},
    )
    return None
  return restored


def hydrate_registry_from_memories(
  memories: Any,
  *,
  registry: AgentRegistry | None = None,
) -> list[str]:
  registry = registry or AgentRegistry()
  hydrated_ids: list[str] = []
  for memory in list_value(memories):
    if not isinstance(memory, dict):
      continue
    if memory.get("key") != "latest_dynamic_agent_registry" and memory.get("kind") != "agent_registry":
      continue
    try:
      snapshot = json.loads(text_value(memory.get("content")))
    except (TypeError, ValueError, json.JSONDecodeError):
      continue
    for raw_agent in list_value(object_value(snapshot).get("agents")):
      if not isinstance(raw_agent, dict):
        continue
      agent_id = slug(raw_agent.get("id"))
      capabilities = unique_strings([slug(item) for item in string_list(raw_agent.get("capabilities")) if slug(item)])
      if not agent_id or agent_id in registry.agents or not capabilities:
        continue
      if any(is_non_creatable_agent_capability(capability) for capability in capabilities):
        log_dynamic_agent_event(
          "agent.memory_hydration_rejected",
          status="rejected",
          payload={
            "agent_id": agent_id,
            "owner_user_id": registry.owner_user_id,
            "reasons": [
              "non_creatable_capabilities:"
              + ",".join(sorted(capability for capability in capabilities if is_non_creatable_agent_capability(capability)))
            ],
          },
        )
        continue
      if is_project_specific_agent_prompt(raw_agent.get("system_prompt")):
        log_dynamic_agent_event(
          "agent.memory_hydration_rejected",
          status="rejected",
          payload={
            "agent_id": agent_id,
            "owner_user_id": registry.owner_user_id,
            "reasons": ["project_specific_system_prompt"],
          },
        )
        continue
      metrics = object_value(raw_agent.get("metrics"))
      successful_runs = int(metrics.get("successful_runs") or 0)
      definition = AgentDefinition(
        id=agent_id,
        name=text_value(raw_agent.get("name")) or title_name(agent_id),
        role=text_value(raw_agent.get("role")) or f"Provide {capabilities[0]} recommendations.",
        capabilities=capabilities[:6],
        system_prompt=text_value(raw_agent.get("system_prompt")) or (
          f"You are the {title_name(agent_id)}. Return structured recommendations only."
        ),
        tools=list(ALLOWED_DYNAMIC_TOOLS),
        supported_domains=unique_strings(
          [slug(item) for item in string_list(raw_agent.get("supported_domains")) if slug(item)]
        )[:6] or ["any"],
        constraints={
          "max_tokens": AGENT_BUDGETS.specialist_output_tokens,
          "temperature": 0.2,
          "python_tool_execution_only": True,
          "direct_file_writes": False,
        },
        metrics={
          **default_dynamic_metrics(),
          **metrics,
          "usage_count": max(int(metrics.get("usage_count") or successful_runs), successful_runs),
          "success_rate": float(metrics.get("success_rate") or (1.0 if successful_runs else 0.0)),
          "successful_runs": successful_runs,
        },
        lifecycle="reusable" if successful_runs >= dynamic_agent_promotion_min_successes() else "experimental",
        owner_user_id=registry.owner_user_id,
        allowed_tools=list(ALLOWED_DYNAMIC_TOOLS),
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
          "agent.memory_hydration_rejected",
          status="rejected",
          payload={
            "agent_id": definition.id,
            "owner_user_id": definition.owner_user_id,
            "reasons": rejection_reasons,
          },
        )
        continue
      registry.register(definition)
      hydrated_ids.append(definition.id)
      log_dynamic_agent_event(
        "agent.hydrated_from_memory",
        payload={"agent_id": definition.id, "owner_user_id": definition.owner_user_id},
      )
  return hydrated_ids


def reset_global_agent_registry() -> AgentRegistry:
  """Deprecated compatibility helper; no process-global registry is retained."""
  return AgentRegistry()
