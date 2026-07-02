from __future__ import annotations

from typing import Any

CHIEF_SUPERVISOR = "chief_supervisor"

CONTEXT_TEAM = "team_context"
ANALYSIS_TEAM = "team_analysis"
PLANNING_TEAM = "team_planning"
DYNAMIC_AGENTS_TEAM = "team_dynamic_agents"
GENERATION_TEAM = "team_generation"
VERIFICATION_TEAM = "team_verification"
COMMIT_TEAM = "team_commit"

TEAM_IDS: tuple[str, ...] = (
  CONTEXT_TEAM,
  ANALYSIS_TEAM,
  PLANNING_TEAM,
  DYNAMIC_AGENTS_TEAM,
  GENERATION_TEAM,
  VERIFICATION_TEAM,
  COMMIT_TEAM,
)

TEAM_LABELS: dict[str, str] = {
  CONTEXT_TEAM: "Context Team",
  ANALYSIS_TEAM: "Analysis Team",
  PLANNING_TEAM: "Planning Team",
  DYNAMIC_AGENTS_TEAM: "Dynamic Agents Team",
  GENERATION_TEAM: "Generation Team",
  VERIFICATION_TEAM: "Verification Team",
  COMMIT_TEAM: "Commit Team",
}

# Dynamic spawn lifecycle: planner creates agents → specialists execute via LangGraph Send → patch integrator merges candidates.
DYNAMIC_SPAWN_ACTIONS: frozenset[str] = frozenset(
  {
    "RUN_DYNAMIC_AGENT_PLANNER",
    "RUN_DYNAMIC_SPECIALISTS",
    "RUN_DYNAMIC_PATCH_INTEGRATOR",
  }
)

ACTION_TO_TEAM: dict[str, str] = {
  "READ_PROJECT_FILES": CONTEXT_TEAM,
  "LOAD_PROJECT_MEMORY": CONTEXT_TEAM,
  "RUN_PARALLEL_PROJECT_BOOTSTRAP": CONTEXT_TEAM,
  "RUN_UPDATE_ANALYST": ANALYSIS_TEAM,
  "RUN_ERROR_HANDLING_AGENT": ANALYSIS_TEAM,
  "RUN_PROMPT_ANALYST": ANALYSIS_TEAM,
  "RUN_PLANNER": PLANNING_TEAM,
  "RUN_DYNAMIC_AGENT_PLANNER": DYNAMIC_AGENTS_TEAM,
  "RUN_DYNAMIC_SPECIALISTS": DYNAMIC_AGENTS_TEAM,
  "RUN_DYNAMIC_PATCH_INTEGRATOR": DYNAMIC_AGENTS_TEAM,
  "RUN_CODE_AGENT": GENERATION_TEAM,
  "RUN_REPAIR_AGENT": GENERATION_TEAM,
  "RUN_SCOPED_UPDATE_AGENT": GENERATION_TEAM,
  "MATERIALIZE_CANDIDATE_FILES": GENERATION_TEAM,
  "RUN_UX_REVIEW_AGENT": VERIFICATION_TEAM,
  "RUN_ACCESSIBILITY_AGENT": VERIFICATION_TEAM,
  "RUN_PARALLEL_REVIEW_AGENTS": VERIFICATION_TEAM,
  "VALIDATE_PROJECT_ARTIFACT": VERIFICATION_TEAM,
  "BUILD_STAGED_PROJECT_PREVIEW": VERIFICATION_TEAM,
  "RUN_PREVIEW_VISUAL_QA": VERIFICATION_TEAM,
  "WRITE_PROJECT_FILES": COMMIT_TEAM,
  "PERSIST_PROJECT_MEMORY": COMMIT_TEAM,
}

TEAM_MAX_BATCH_ACTIONS = 12


def team_for_action(action: str) -> str | None:
  return ACTION_TO_TEAM.get(str(action or ""))


def team_label(team_id: str) -> str:
  return TEAM_LABELS.get(team_id, team_id)


def resolve_pending_team(state: dict[str, Any]) -> str | None:
  return team_for_action(str(state.get("_pending_action") or ""))


def available_actions_for_team(available_actions: list[dict[str, Any]], team_id: str) -> list[str]:
  names: list[str] = []
  for item in available_actions:
    if not isinstance(item, dict):
      continue
    action = str(item.get("action") or "")
    if team_for_action(action) == team_id:
      names.append(action)
  return names
