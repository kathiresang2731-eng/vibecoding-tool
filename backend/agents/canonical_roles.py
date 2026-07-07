from __future__ import annotations

from typing import Any


CANONICAL_ORCHESTRATOR = "Orchestrator"
CANONICAL_CONTEXT_AGENT = "Context Agent"
CANONICAL_WEBSITE_BUILDER = "Website Builder Agent"
CANONICAL_QUALITY_GATE = "Quality Gate Service"
CANONICAL_REPAIR_AGENT = "Repair Agent"
CANONICAL_SAVE_MEMORY = "Save Memory Service"
CANONICAL_LARGE_BUILD_SPECIALISTS = "Large Build Specialist Group"
CANONICAL_SIMPLE_CODE = "Simple Code Writer Agent"
CANONICAL_DOCUMENT_ARTIFACT = "Document Artifact Agent"
CANONICAL_READ_ONLY_ASSISTANT = "Read-only Assistant Agent"


CANONICAL_AGENT_ROLES: dict[str, dict[str, Any]] = {
  CANONICAL_ORCHESTRATOR: {
    "purpose": "Route the user turn and choose the correct branch before any mutation.",
    "visible": True,
  },
  CANONICAL_CONTEXT_AGENT: {
    "purpose": "Load files, memory, project context, and update scope before implementation.",
    "visible": True,
  },
  CANONICAL_WEBSITE_BUILDER: {
    "purpose": "Generate or update website files through the selected internal execution strategy.",
    "visible": True,
  },
  CANONICAL_QUALITY_GATE: {
    "purpose": "Validate artifacts, build previews, and run QA checks before final save.",
    "visible": True,
  },
  CANONICAL_REPAIR_AGENT: {
    "purpose": "Repair candidate code only after validation, build, preview, or runtime failure.",
    "visible": True,
  },
  CANONICAL_SAVE_MEMORY: {
    "purpose": "Persist accepted files and store the completed run memory.",
    "visible": True,
  },
  CANONICAL_LARGE_BUILD_SPECIALISTS: {
    "purpose": "Optional read/planning specialists for large CRM, SaaS, dashboard, or multi-module builds.",
    "visible": False,
  },
  CANONICAL_SIMPLE_CODE: {
    "purpose": "Generate standalone code artifacts outside the website runtime.",
    "visible": True,
  },
  CANONICAL_DOCUMENT_ARTIFACT: {
    "purpose": "Generate document artifacts such as Markdown, TXT, CSV, and PDF-ready content.",
    "visible": True,
  },
  CANONICAL_READ_ONLY_ASSISTANT: {
    "purpose": "Answer conversation, project-info, and general-query turns without file mutation.",
    "visible": True,
  },
}


AGENT_TO_CANONICAL_ROLE: dict[str, str] = {
  "Intent Router Agent": CANONICAL_ORCHESTRATOR,
  "Requirement Confirmation Agent": CANONICAL_ORCHESTRATOR,
  "Conversation Agent": CANONICAL_READ_ONLY_ASSISTANT,
  "Read-only Assistant Agent": CANONICAL_READ_ONLY_ASSISTANT,
  "Simple Code Writer Agent": CANONICAL_SIMPLE_CODE,
  "Document Artifact Agent": CANONICAL_DOCUMENT_ARTIFACT,
  "Memory Agent": CANONICAL_CONTEXT_AGENT,
  "Universal Error Handling Agent": CANONICAL_CONTEXT_AGENT,
  "Update Analysis Agent": CANONICAL_CONTEXT_AGENT,
  "Prompt Analyst Agent": CANONICAL_CONTEXT_AGENT,
  "Planner Agent": CANONICAL_CONTEXT_AGENT,
  "Predictive Planning Agent": CANONICAL_CONTEXT_AGENT,
  "Project Context Agent": CANONICAL_CONTEXT_AGENT,
  "Diagnostic UX Agent": CANONICAL_QUALITY_GATE,
  "UX Review Agent": CANONICAL_QUALITY_GATE,
  "Accessibility Agent": CANONICAL_QUALITY_GATE,
  "Validation Agent": CANONICAL_QUALITY_GATE,
  "Preview Agent": CANONICAL_QUALITY_GATE,
  "Preview QA Agent": CANONICAL_QUALITY_GATE,
  "Visual QA Agent": CANONICAL_QUALITY_GATE,
  "Prescriptive Builder Agent": CANONICAL_WEBSITE_BUILDER,
  "Streaming File Agent": CANONICAL_WEBSITE_BUILDER,
  "Greenfield Generation Engine": CANONICAL_WEBSITE_BUILDER,
  "Parallel Stream Orchestrator": CANONICAL_WEBSITE_BUILDER,
  "Parallel File Orchestrator": CANONICAL_WEBSITE_BUILDER,
  "Main Coding Agent": CANONICAL_WEBSITE_BUILDER,
  "Code Agent": CANONICAL_WEBSITE_BUILDER,
  "Code Generator Agent": CANONICAL_WEBSITE_BUILDER,
  "Scoped Update Agent": CANONICAL_WEBSITE_BUILDER,
  "Targeted Update Agent": CANONICAL_WEBSITE_BUILDER,
  "Materialize Agent": CANONICAL_WEBSITE_BUILDER,
  "Repair Agent": CANONICAL_REPAIR_AGENT,
  "Commit Agent": CANONICAL_SAVE_MEMORY,
  "Supervisor Agent": CANONICAL_ORCHESTRATOR,
  "Agent Registry Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Content Specialist Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Layout Specialist Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Catalog Specialist Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Domain Research Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Requirement Analyst Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Task Decomposer Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Workflow Planner Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
  "Component/UI Agent": CANONICAL_LARGE_BUILD_SPECIALISTS,
}


def canonical_role_for_agent(agent_name: str | None) -> str:
  name = str(agent_name or "").strip()
  return AGENT_TO_CANONICAL_ROLE.get(name, name or "Unknown Agent")


def canonical_role_policy(role_name: str | None) -> dict[str, Any]:
  role = canonical_role_for_agent(role_name)
  return dict(CANONICAL_AGENT_ROLES.get(role, {"purpose": "", "visible": True}))


def canonicalize_agent_entry(entry: dict[str, Any]) -> dict[str, Any]:
  agent_name = str(entry.get("name") or "").strip()
  canonical_role = canonical_role_for_agent(agent_name)
  return {
    **entry,
    "canonical_role": canonical_role,
    "internal_agent": agent_name,
    "canonical_role_purpose": canonical_role_policy(canonical_role).get("purpose", ""),
  }


def canonicalize_agent_list(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
  return [
    canonicalize_agent_entry(entry)
    for entry in entries
    if isinstance(entry, dict)
  ]


def canonicalize_progress_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
  payload = dict(detail or {})
  selected_agent = str(payload.get("selected_agent") or payload.get("agent") or "").strip()
  selected_agents = [
    str(item).strip()
    for item in list(payload.get("selected_agents") or [])
    if str(item).strip()
  ]
  if selected_agent:
    payload.setdefault("internal_agent", selected_agent)
    payload["canonical_role"] = canonical_role_for_agent(selected_agent)
  elif selected_agents:
    canonical_roles = list(dict.fromkeys(canonical_role_for_agent(name) for name in selected_agents))
    payload.setdefault("internal_agents", selected_agents)
    payload["canonical_roles"] = canonical_roles
    if len(canonical_roles) == 1:
      payload["canonical_role"] = canonical_roles[0]
  return payload


def canonical_agent_display(agent_name: str | None) -> str:
  name = str(agent_name or "").strip()
  canonical_role = canonical_role_for_agent(name)
  if not name or name == canonical_role:
    return canonical_role
  return f"{canonical_role} ({name})"


def runtime_step_tool_label(step: dict[str, Any]) -> str:
  tool_names = [
    str(item).strip()
    for item in (step.get("tool_calls") if isinstance(step.get("tool_calls"), list) else [])
    if str(item).strip()
  ]
  direct_tool = str(step.get("tool") or "").strip()
  if direct_tool:
    tool_names.append(direct_tool)
  action_name = str(step.get("action") or step.get("next_action") or "").strip()
  return ", ".join(dict.fromkeys(tool_names)) or action_name or "no_tool_recorded"


def compact_runtime_step_projection(steps: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> dict[str, list[str]]:
  """Return duplicate-safe runtime log fields.

  runtime_steps is intentionally the compact visible phase list.
  runtime_internal_steps preserves the exact backend agents that executed.
  runtime_step_details and runtime_phase_details preserve agent -> tool/action proof.
  """
  visible_roles: list[str] = []
  internal_agents: list[str] = []
  step_details: list[str] = []
  phase_details: list[str] = []
  grouped: dict[str, list[str]] = {}

  for step in list(steps or []):
    if not isinstance(step, dict):
      continue
    internal_agent = str(
      step.get("internal_agent")
      or step.get("agent")
      or step.get("name")
      or step.get("step")
      or ""
    ).strip()
    if not internal_agent:
      continue
    visible_role = str(step.get("canonical_role") or step.get("agent") or "").strip()
    visible_role = canonical_role_for_agent(visible_role or internal_agent)
    tool_label = runtime_step_tool_label(step)

    if visible_role not in visible_roles:
      visible_roles.append(visible_role)
    internal_agents.append(internal_agent)
    step_details.append(f"{internal_agent} -> {tool_label}")
    grouped.setdefault(visible_role, []).append(f"{internal_agent} -> {tool_label}")

  for role, details in grouped.items():
    phase_details.append(f"{role}:")
    phase_details.extend(f"  - {detail}" for detail in details)

  return {
    "runtime_steps": visible_roles,
    "runtime_internal_steps": internal_agents,
    "runtime_step_details": step_details,
    "runtime_phase_details": phase_details,
  }
