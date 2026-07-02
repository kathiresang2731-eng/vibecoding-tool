from __future__ import annotations

from typing import Any

from ..graph_runtime.hierarchical_teams import (
  ANALYSIS_TEAM,
  COMMIT_TEAM,
  CONTEXT_TEAM,
  DYNAMIC_AGENTS_TEAM,
  GENERATION_TEAM,
  PLANNING_TEAM,
  TEAM_LABELS,
  VERIFICATION_TEAM,
  team_for_action,
  team_label,
)
from ..runtime_agents.registry import ACTION_REGISTRY, RUNTIME_AGENT_GROUPS


FLOW_PHASES: tuple[dict[str, Any], ...] = (
  {
    "id": "1_context",
    "title": "Phase 1 — Context Team",
    "team": CONTEXT_TEAM,
    "agents": ("Memory Agent",),
    "description": "Read project files and load memory before planning.",
  },
  {
    "id": "2_analysis",
    "title": "Phase 2 — Analysis Team",
    "team": ANALYSIS_TEAM,
    "agents": ("Universal Error Handling Agent", "Update Analysis Agent", "Prompt Analyst Agent"),
    "description": "Diagnose errors, analyze updates, or create the website brief.",
  },
  {
    "id": "3_planning",
    "title": "Phase 3 — Planning Team",
    "team": PLANNING_TEAM,
    "agents": ("Planner Agent",),
    "description": "Turn the brief into a section and implementation plan.",
  },
  {
    "id": "4_dynamic",
    "title": "Phase 4 — Dynamic Agents Team",
    "team": DYNAMIC_AGENTS_TEAM,
    "agents": ("Agent Registry Agent",),
    "description": "Spawn specialists, execute them in parallel, integrate candidate patches.",
  },
  {
    "id": "5_generation",
    "title": "Phase 5 — Generation Team",
    "team": GENERATION_TEAM,
    "agents": (
      "Scoped Update Agent",
      "Code Agent",
      "Repair Agent",
      "Code Generator Agent",
      "Materialize Agent",
    ),
    "description": "Generate or patch code and materialize candidate files.",
  },
  {
    "id": "6_verification",
    "title": "Phase 6 — Verification Team",
    "team": VERIFICATION_TEAM,
    "agents": (
      "UX Review Agent",
      "Accessibility Agent",
      "Validation Agent",
      "Preview Agent",
      "Visual QA Agent",
    ),
    "description": "Review, validate, build preview, and run visual QA.",
  },
  {
    "id": "7_commit",
    "title": "Phase 7 — Commit Team",
    "team": COMMIT_TEAM,
    "agents": ("Commit Agent", "Memory Agent"),
    "description": "Write files and persist project memory.",
  },
)


AGENT_SCRIPT_NAMES: dict[str, str] = {
  "Memory Agent": "memory_agent",
  "Universal Error Handling Agent": "error_handling_agent",
  "Update Analysis Agent": "update_analysis_agent",
  "Scoped Update Agent": "scoped_update_agent",
  "Prompt Analyst Agent": "prompt_analyst_agent",
  "Planner Agent": "planner_agent",
  "Agent Registry Agent": "agent_registry_agent",
  "UX Review Agent": "ux_review_agent",
  "Accessibility Agent": "accessibility_agent",
  "Code Agent": "code_agent",
  "Code Generator Agent": "code_generator_agent",
  "Materialize Agent": "materialize_agent",
  "Repair Agent": "repair_agent",
  "Validation Agent": "validation_agent",
  "Preview Agent": "preview_agent",
  "Visual QA Agent": "visual_qa_agent",
  "Commit Agent": "commit_agent",
}


def actions_for_agent_name(agent_name: str) -> list[str]:
  return list(RUNTIME_AGENT_GROUPS.get(agent_name, ()))


def phase_for_agent(agent_name: str) -> dict[str, Any] | None:
  for phase in FLOW_PHASES:
    if agent_name in phase["agents"]:
      return phase
  return None


def team_for_agent_name(agent_name: str) -> str | None:
  actions = actions_for_agent_name(agent_name)
  if not actions:
    return None
  return team_for_action(actions[0])


def agent_catalog_entry(agent_name: str) -> dict[str, Any]:
  actions = actions_for_agent_name(agent_name)
  phase = phase_for_agent(agent_name)
  return {
    "agent": agent_name,
    "actions": actions,
    "phase": phase["id"] if phase else None,
    "phase_title": phase["title"] if phase else None,
    "team": team_for_agent_name(agent_name),
    "team_label": team_label(team_for_agent_name(agent_name) or ""),
    "script": f"{AGENT_SCRIPT_NAMES.get(agent_name, 'run_agent')}.py",
    "action_details": [
      {
        "action": action,
        "description": ACTION_REGISTRY.get(action, {}).get("description", ""),
        "tools": ACTION_REGISTRY.get(action, {}).get("tools", []),
      }
      for action in actions
    ],
  }


def list_all_agents() -> list[str]:
  return [name for name in RUNTIME_AGENT_GROUPS if name != "Supervisor Agent"]


def phase_agents(phase_id: str) -> list[str]:
  for phase in FLOW_PHASES:
    if phase["id"] == phase_id:
      return list(phase["agents"])
  return []


def format_phase_menu() -> str:
  lines = ["Worktual agent flow (phase-wise):", ""]
  for phase in FLOW_PHASES:
    lines.append(f"{phase['title']}")
    lines.append(f"  Team: {TEAM_LABELS.get(phase['team'], phase['team'])}")
    lines.append(f"  Agents: {', '.join(phase['agents'])}")
    lines.append(f"  {phase['description']}")
    lines.append("")
  return "\n".join(lines)
