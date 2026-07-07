from __future__ import annotations

from typing import Any

from ..canonical_roles import canonical_role_for_agent
from ..agent_tool_catalog import RUNTIME_ACTION_DESCRIPTIONS


def _action(agent: str, action: str, tools: list[str] | None = None) -> dict[str, Any]:
  return {
    "agent": agent,
    "internal_agent": agent,
    "canonical_role": canonical_role_for_agent(agent),
    "description": RUNTIME_ACTION_DESCRIPTIONS[action],
    "tools": list(tools or []),
  }


# Human-facing runtime map: agent -> legal action -> tool contract.
# The supervisor imports this registry so the explainable map and executable
# flow cannot drift apart.
ACTION_REGISTRY: dict[str, dict[str, Any]] = {
  "READ_PROJECT_FILES": _action("Memory Agent", "READ_PROJECT_FILES", ["READ_PROJECT_FILES"]),
  "LOAD_PROJECT_MEMORY": _action("Memory Agent", "LOAD_PROJECT_MEMORY", ["LOAD_PROJECT_MEMORY"]),
  "RUN_PARALLEL_PROJECT_BOOTSTRAP": _action(
    "Memory Agent",
    "RUN_PARALLEL_PROJECT_BOOTSTRAP",
    ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"],
  ),
  "RUN_UPDATE_ANALYST": _action("Update Analysis Agent", "RUN_UPDATE_ANALYST"),
  "RUN_ERROR_HANDLING_AGENT": _action("Universal Error Handling Agent", "RUN_ERROR_HANDLING_AGENT"),
  "RUN_SCOPED_UPDATE_AGENT": _action("Scoped Update Agent", "RUN_SCOPED_UPDATE_AGENT"),
  "RUN_PROMPT_ANALYST": _action("Prompt Analyst Agent", "RUN_PROMPT_ANALYST"),
  "RUN_PLANNER": _action("Planner Agent", "RUN_PLANNER"),
  "RUN_DYNAMIC_AGENT_PLANNER": _action("Agent Registry Agent", "RUN_DYNAMIC_AGENT_PLANNER"),
  "RUN_DYNAMIC_SPECIALISTS": _action("Agent Registry Agent", "RUN_DYNAMIC_SPECIALISTS"),
  "RUN_UX_REVIEW_AGENT": _action("UX Review Agent", "RUN_UX_REVIEW_AGENT"),
  "RUN_ACCESSIBILITY_AGENT": _action("Accessibility Agent", "RUN_ACCESSIBILITY_AGENT"),
  "RUN_PARALLEL_REVIEW_AGENTS": _action("UX Review Agent", "RUN_PARALLEL_REVIEW_AGENTS"),
  "RUN_CODE_AGENT": _action("Code Agent", "RUN_CODE_AGENT"),
  "RUN_DYNAMIC_PATCH_INTEGRATOR": _action("Code Generator Agent", "RUN_DYNAMIC_PATCH_INTEGRATOR"),
  "MATERIALIZE_CANDIDATE_FILES": _action("Materialize Agent", "MATERIALIZE_CANDIDATE_FILES"),
  "RUN_REPAIR_AGENT": _action("Repair Agent", "RUN_REPAIR_AGENT"),
  "VALIDATE_PROJECT_ARTIFACT": _action("Validation Agent", "VALIDATE_PROJECT_ARTIFACT", ["VALIDATE_PROJECT_ARTIFACT"]),
  "BUILD_STAGED_PROJECT_PREVIEW": _action("Preview Agent", "BUILD_STAGED_PROJECT_PREVIEW", ["BUILD_STAGED_PROJECT_PREVIEW"]),
  "RUN_PREVIEW_VISUAL_QA": _action("Visual QA Agent", "RUN_PREVIEW_VISUAL_QA", ["RUN_PREVIEW_VISUAL_QA"]),
  "WRITE_PROJECT_FILES": _action("Commit Agent", "WRITE_PROJECT_FILES", ["WRITE_PROJECT_FILES"]),
  "PERSIST_PROJECT_MEMORY": _action("Memory Agent", "PERSIST_PROJECT_MEMORY", ["PERSIST_PROJECT_MEMORY"]),
  "DONE": _action("Supervisor Agent", "DONE"),
}


RUNTIME_AGENT_GROUPS: dict[str, tuple[str, ...]] = {
  "Memory Agent": ("READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "RUN_PARALLEL_PROJECT_BOOTSTRAP", "PERSIST_PROJECT_MEMORY"),
  "Universal Error Handling Agent": ("RUN_ERROR_HANDLING_AGENT",),
  "Update Analysis Agent": ("RUN_UPDATE_ANALYST",),
  "Scoped Update Agent": ("RUN_SCOPED_UPDATE_AGENT",),
  "Prompt Analyst Agent": ("RUN_PROMPT_ANALYST",),
  "Planner Agent": ("RUN_PLANNER",),
  "Agent Registry Agent": ("RUN_DYNAMIC_AGENT_PLANNER", "RUN_DYNAMIC_SPECIALISTS"),
  "UX Review Agent": ("RUN_UX_REVIEW_AGENT", "RUN_PARALLEL_REVIEW_AGENTS"),
  "Accessibility Agent": ("RUN_ACCESSIBILITY_AGENT",),
  "Code Agent": ("RUN_CODE_AGENT",),
  "Code Generator Agent": ("RUN_DYNAMIC_PATCH_INTEGRATOR",),
  "Materialize Agent": ("MATERIALIZE_CANDIDATE_FILES",),
  "Repair Agent": ("RUN_REPAIR_AGENT",),
  "Validation Agent": ("VALIDATE_PROJECT_ARTIFACT",),
  "Preview Agent": ("BUILD_STAGED_PROJECT_PREVIEW",),
  "Visual QA Agent": ("RUN_PREVIEW_VISUAL_QA",),
  "Commit Agent": ("WRITE_PROJECT_FILES",),
  "Supervisor Agent": ("DONE",),
}


AGENT_FLOW: tuple[dict[str, Any], ...] = (
  {"phase": "intake", "agents": ("Memory Agent",)},
  {"phase": "update-routing", "agents": ("Universal Error Handling Agent", "Update Analysis Agent")},
  {"phase": "generation-planning", "agents": ("Prompt Analyst Agent", "Planner Agent", "Agent Registry Agent")},
  {"phase": "implementation", "agents": ("Scoped Update Agent", "Code Agent", "Repair Agent", "Code Generator Agent", "Materialize Agent")},
  {"phase": "quality-gates", "agents": ("UX Review Agent", "Accessibility Agent", "Validation Agent", "Preview Agent", "Visual QA Agent")},
  {"phase": "commit-memory", "agents": ("Commit Agent", "Memory Agent", "Supervisor Agent")},
)


def runtime_agent_names() -> list[str]:
  return list(RUNTIME_AGENT_GROUPS)


def canonical_runtime_agent_groups() -> dict[str, tuple[str, ...]]:
  grouped: dict[str, list[str]] = {}
  for agent_name, actions in RUNTIME_AGENT_GROUPS.items():
    role = canonical_role_for_agent(agent_name)
    grouped.setdefault(role, [])
    for action in actions:
      if action not in grouped[role]:
        grouped[role].append(action)
  return {role: tuple(actions) for role, actions in grouped.items()}


def actions_for_agent(agent_name: str) -> list[dict[str, Any]]:
  return [
    {"action": action, **ACTION_REGISTRY[action]}
    for action in RUNTIME_AGENT_GROUPS.get(agent_name, ())
  ]
