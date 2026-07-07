from __future__ import annotations

from backend.agents.agent_tool_catalog import DEFAULT_AGENT_TEAM, FULL_AGENT_REGISTRY, INTERNAL_AGENT_REGISTRY, VISIBLE_AGENT_TEAM
from backend.agents.canonical_roles import (
  CANONICAL_CONTEXT_AGENT,
  CANONICAL_ORCHESTRATOR,
  CANONICAL_QUALITY_GATE,
  CANONICAL_SAVE_MEMORY,
  CANONICAL_WEBSITE_BUILDER,
  canonical_agent_display,
  canonical_role_for_agent,
  canonicalize_progress_detail,
  compact_runtime_step_projection,
)
from backend.agents.runtime_agents.registry import ACTION_REGISTRY, canonical_runtime_agent_groups


def test_known_duplicate_agents_map_to_canonical_roles() -> None:
  assert canonical_role_for_agent("Prompt Analyst Agent") == CANONICAL_CONTEXT_AGENT
  assert canonical_role_for_agent("Update Analysis Agent") == CANONICAL_CONTEXT_AGENT
  assert canonical_role_for_agent("Streaming File Agent") == CANONICAL_WEBSITE_BUILDER
  assert canonical_role_for_agent("Scoped Update Agent") == CANONICAL_WEBSITE_BUILDER
  assert canonical_role_for_agent("Validation Agent") == CANONICAL_QUALITY_GATE
  assert canonical_role_for_agent("Preview Agent") == CANONICAL_QUALITY_GATE
  assert canonical_role_for_agent("Commit Agent") == CANONICAL_SAVE_MEMORY
  assert canonical_role_for_agent("Supervisor Agent") == CANONICAL_ORCHESTRATOR


def test_default_agent_team_is_visible_only_and_internal_registry_keeps_execution_agents() -> None:
  visible_names = [item["name"] for item in DEFAULT_AGENT_TEAM]
  assert DEFAULT_AGENT_TEAM == VISIBLE_AGENT_TEAM
  assert len(visible_names) < 12
  assert CANONICAL_CONTEXT_AGENT in visible_names
  assert CANONICAL_WEBSITE_BUILDER in visible_names
  assert "Prompt Analyst Agent" not in visible_names
  assert "Streaming File Agent" not in visible_names

  prompt_analyst = next(item for item in INTERNAL_AGENT_REGISTRY if item["name"] == "Prompt Analyst Agent")
  streaming_agent = next(item for item in INTERNAL_AGENT_REGISTRY if item["name"] == "Streaming File Agent")

  assert prompt_analyst["internal_agent"] == "Prompt Analyst Agent"
  assert prompt_analyst["canonical_role"] == CANONICAL_CONTEXT_AGENT
  assert streaming_agent["internal_agent"] == "Streaming File Agent"
  assert streaming_agent["canonical_role"] == CANONICAL_WEBSITE_BUILDER
  assert any(item["name"] == "Prompt Analyst Agent" for item in FULL_AGENT_REGISTRY)


def test_runtime_action_registry_exposes_canonical_role_without_losing_agent() -> None:
  action = ACTION_REGISTRY["RUN_SCOPED_UPDATE_AGENT"]

  assert action["agent"] == "Scoped Update Agent"
  assert action["internal_agent"] == "Scoped Update Agent"
  assert action["canonical_role"] == CANONICAL_WEBSITE_BUILDER


def test_runtime_actions_collapse_into_canonical_groups() -> None:
  grouped = canonical_runtime_agent_groups()

  assert "RUN_PROMPT_ANALYST" in grouped[CANONICAL_CONTEXT_AGENT]
  assert "RUN_UPDATE_ANALYST" in grouped[CANONICAL_CONTEXT_AGENT]
  assert "RUN_CODE_AGENT" in grouped[CANONICAL_WEBSITE_BUILDER]
  assert "RUN_SCOPED_UPDATE_AGENT" in grouped[CANONICAL_WEBSITE_BUILDER]
  assert "VALIDATE_PROJECT_ARTIFACT" in grouped[CANONICAL_QUALITY_GATE]
  assert "BUILD_STAGED_PROJECT_PREVIEW" in grouped[CANONICAL_QUALITY_GATE]


def test_progress_detail_adds_canonical_role_for_terminal_logs() -> None:
  detail = canonicalize_progress_detail(
    {
      "selected_agent": "Streaming File Agent",
      "workflow": "streaming_file_agent",
    }
  )

  assert detail["internal_agent"] == "Streaming File Agent"
  assert detail["canonical_role"] == CANONICAL_WEBSITE_BUILDER
  assert canonical_agent_display("Streaming File Agent") == "Website Builder Agent (Streaming File Agent)"


def test_runtime_projection_collapses_visible_duplicate_agents_but_keeps_tool_details() -> None:
  projection = compact_runtime_step_projection(
    [
      {
        "agent": "Context Agent",
        "canonical_role": "Context Agent",
        "internal_agent": "Prompt Analyst Agent",
        "action": "extract_website_brief",
        "tool_calls": [],
      },
      {
        "agent": "Context Agent",
        "canonical_role": "Context Agent",
        "internal_agent": "Planner Agent",
        "action": "plan_sections",
        "tool_calls": [],
      },
      {
        "agent": "Website Builder Agent",
        "canonical_role": "Website Builder Agent",
        "internal_agent": "Scoped Update Agent",
        "action": "patch_target_files",
        "tool_calls": ["RUN_SCOPED_UPDATE_AGENT"],
      },
      {
        "agent": "Quality Gate Service",
        "canonical_role": "Quality Gate Service",
        "internal_agent": "Validation Agent",
        "action": "validate",
        "tool_calls": ["VALIDATE_PROJECT_ARTIFACT"],
      },
    ]
  )

  assert projection["runtime_steps"] == [
    CANONICAL_CONTEXT_AGENT,
    CANONICAL_WEBSITE_BUILDER,
    CANONICAL_QUALITY_GATE,
  ]
  assert projection["runtime_internal_steps"] == [
    "Prompt Analyst Agent",
    "Planner Agent",
    "Scoped Update Agent",
    "Validation Agent",
  ]
  assert projection["runtime_step_details"] == [
    "Prompt Analyst Agent -> extract_website_brief",
    "Planner Agent -> plan_sections",
    "Scoped Update Agent -> RUN_SCOPED_UPDATE_AGENT",
    "Validation Agent -> VALIDATE_PROJECT_ARTIFACT",
  ]
  assert projection["runtime_phase_details"] == [
    "Context Agent:",
    "  - Prompt Analyst Agent -> extract_website_brief",
    "  - Planner Agent -> plan_sections",
    "Website Builder Agent:",
    "  - Scoped Update Agent -> RUN_SCOPED_UPDATE_AGENT",
    "Quality Gate Service:",
    "  - Validation Agent -> VALIDATE_PROJECT_ARTIFACT",
  ]
