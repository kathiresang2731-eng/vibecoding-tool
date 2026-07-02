from __future__ import annotations

from backend.llm.terminal_runners.catalog import (
  FLOW_PHASES,
  actions_for_agent_name,
  agent_catalog_entry,
  phase_for_agent,
  team_for_agent_name,
)
from backend.llm.terminal_runners.executor import run_agent_actions
from backend.llm.terminal_runners.seeds import seed_state_for_agent


def test_planner_agent_catalog():
  entry = agent_catalog_entry("Planner Agent")
  assert entry["actions"] == ["RUN_PLANNER"]
  assert entry["phase"] == "3_planning"
  assert team_for_agent_name("Planner Agent") == "team_planning"


def test_run_planner_agent_terminal_mock():
  state = run_agent_actions(
    agent_name="Planner Agent",
    prompt="generate the code for farm website",
    provider_mode="mock",
  )
  assert "RUN_PLANNER" in (state.get("action_history") or [])
  assert isinstance(state.get("plan"), dict)


def test_seed_state_for_prompt_analyst():
  state = seed_state_for_agent(
    agent_name="Prompt Analyst Agent",
    prompt="build a farm website",
  )
  assert state.get("read_result") is not None
  assert state.get("brief") is None


def test_dynamic_registry_seed_mode():
  state = seed_state_for_agent(
    agent_name="Agent Registry Agent",
    prompt="farm website",
    seed_mode="dynamic_planner",
  )
  assert state.get("dynamic_workflow_plan") is None
  assert state.get("brief") is not None
  assert state.get("plan") is not None


def test_flow_phases_cover_all_teams():
  teams = {phase["team"] for phase in FLOW_PHASES}
  assert "team_dynamic_agents" in teams
  assert len(FLOW_PHASES) == 7
