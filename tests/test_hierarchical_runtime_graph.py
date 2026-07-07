from __future__ import annotations

from backend.llm.agent_runtime.actions.dispatcher import ACTION_HANDLERS
from backend.llm.agent_runtime.loop_core import RuntimeLoopParams
from backend.llm.agent_runtime.state import initial_runtime_state
from backend.llm.graph_runtime.a2a.bus import publish_dynamic_agent_spawns, publish_team_handoff
from backend.llm.graph_runtime.dynamic_spawn_runtime import (
  collect_spawned_agents_from_state,
  dynamic_spawning_needed,
  sync_dynamic_spawn_state,
)
from backend.llm.graph_runtime.hierarchical_edges import route_after_chief
from backend.llm.graph_runtime.hierarchical_runtime_graph import (
  compile_hierarchical_runtime_graph,
  hierarchical_graph_topology,
)
from backend.llm.graph_runtime.hierarchical_teams import (
  ACTION_TO_TEAM,
  CHIEF_SUPERVISOR,
  DYNAMIC_AGENTS_TEAM,
  DYNAMIC_SPAWN_ACTIONS,
  TEAM_IDS,
  team_for_action,
)
from backend.llm.runtime_config import runtime_graph_topology


def _params(**overrides) -> RuntimeLoopParams:
  base = {
    "project_id": "proj-hierarchical-test",
    "user": type("User", (), {"id": "user-1"})(),
    "tool_context": None,
    "prompt": "Build a landing page",
    "routing_result": {"intent": "website_generation", "confidence": 0.99},
    "control_provider": object(),
    "artifact_provider": object(),
    "prepared_sections": {},
    "progress": lambda *_args, **_kwargs: None,
    "tool_executor": lambda *_args, **_kwargs: {"status": "ok"},
    "repair_attempt_budget": 1,
    "max_steps": 28,
    "max_tool_calls": 18,
    "timeout_seconds": 120,
    "start_time": 0.0,
  }
  base.update(overrides)
  return RuntimeLoopParams(**base)


def test_hierarchical_graph_registers_chief_and_team_nodes():
  app = compile_hierarchical_runtime_graph(_params())
  node_names = set(getattr(app, "nodes", {}).keys())
  assert CHIEF_SUPERVISOR in node_names
  for team_id in TEAM_IDS:
    assert team_id in node_names


def test_all_action_handlers_map_to_teams():
  for action in ACTION_HANDLERS:
    assert team_for_action(action) in TEAM_IDS


def test_route_after_chief_routes_pending_team():
  state = {
    "_pending_action": "READ_PROJECT_FILES",
    "_graph_step_count": 1,
    "_graph_max_steps": 28,
  }
  assert route_after_chief(state) == ACTION_TO_TEAM["READ_PROJECT_FILES"]


def test_publish_team_handoff_records_team_a2a_message():
  state = initial_runtime_state(
    project_id="proj-team-a2a",
    prompt="Build a site",
    routing_result={"intent": "website_generation"},
  )
  state["_pending_action"] = "RUN_PLANNER"
  publish_team_handoff(state, team_id="team_planning", team_label="Planning Team")
  assert len(state["a2a_messages"]) == 1
  assert state["a2a_messages"][0]["to_agent"] == "Planning Team"
  assert state["a2a_messages"][0]["intent"] == "RUN_PLANNER"


def test_runtime_graph_topology_defaults_to_hierarchical_at_high_parity(monkeypatch):
  monkeypatch.delenv("RUNTIME_GRAPH_TOPOLOGY", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert runtime_graph_topology() == "hierarchical"


def test_runtime_graph_topology_honors_explicit_flat_override(monkeypatch):
  monkeypatch.setenv("RUNTIME_GRAPH_TOPOLOGY", "flat")
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert runtime_graph_topology() == "flat"


def test_dynamic_spawn_actions_route_to_dynamic_agents_team():
  for action in DYNAMIC_SPAWN_ACTIONS:
    assert ACTION_TO_TEAM[action] == DYNAMIC_AGENTS_TEAM


def test_route_after_chief_routes_dynamic_spawn_action():
  state = {
    "_pending_action": "RUN_DYNAMIC_AGENT_PLANNER",
    "_graph_step_count": 2,
    "_graph_max_steps": 28,
  }
  assert route_after_chief(state) == DYNAMIC_AGENTS_TEAM


def test_dynamic_spawning_needed_for_full_generation(monkeypatch):
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  state = initial_runtime_state(
    project_id="proj-spawn",
    prompt="Build a SaaS dashboard",
    routing_result={"intent": "website_generation"},
  )
  state["operation"] = "generate"
  state["brief"] = {"summary": "SaaS dashboard"}
  assert dynamic_spawning_needed(state) is True


def test_dynamic_spawning_skipped_for_direct_generation_workflow():
  state = initial_runtime_state(
    project_id="proj-direct",
    prompt="Build a landing page",
    routing_result={"intent": "website_generation"},
  )
  state["operation"] = "generate"
  state["dynamic_workflow_plan"] = {"scope": "direct_generation", "tasks": []}
  assert dynamic_spawning_needed(state) is False


def test_publish_dynamic_agent_spawns_records_a2a_messages():
  state = initial_runtime_state(
    project_id="proj-spawn-a2a",
    prompt="Build a site",
    routing_result={"intent": "website_generation"},
  )
  spawned = [
    {
      "agent_id": "seo-copy-agent",
      "name": "SEO Copy Agent",
      "capabilities": ["seo_copy"],
      "lifecycle": "experimental",
      "assignment_type": "created",
      "task_id": "seo_task",
    }
  ]
  publish_dynamic_agent_spawns(state, spawned)
  assert len(state["a2a_messages"]) == 1
  assert state["a2a_messages"][0]["from_agent"] == "Agent Registry Agent"
  assert state["a2a_messages"][0]["to_agent"] == "SEO Copy Agent"
  assert state["a2a_messages"][0]["intent"] == "RUN_DYNAMIC_SPECIALISTS"


def test_sync_dynamic_spawn_state_builds_spawn_graph_metadata():
  state = initial_runtime_state(
    project_id="proj-spawn-graph",
    prompt="Build a site",
    routing_result={"intent": "website_generation"},
  )
  state["operation"] = "generate"
  state["dynamic_workflow_plan"] = {
    "scope": "website_generation",
    "created_agent_ids": ["hero-copy-agent"],
    "active_agents": [
      {
        "id": "hero-copy-agent",
        "name": "Hero Copy Agent",
        "capabilities": ["hero_copy"],
        "lifecycle": "experimental",
      }
    ],
    "assignments": [
      {
        "task_id": "hero_task",
        "agent_id": "hero-copy-agent",
        "assignment_type": "created",
      }
    ],
    "tasks": [
      {
        "id": "hero_task",
        "runtime_action": "RUN_DYNAMIC_SPECIALISTS",
      }
    ],
    "parallel_groups": [["hero_task"]],
  }
  state = sync_dynamic_spawn_state(state)
  spawned = collect_spawned_agents_from_state(state)
  assert len(spawned) == 1
  assert spawned[0]["agent_id"] == "hero-copy-agent"
  spawn_graph = state["dynamic_spawn_graph"]
  assert spawn_graph["spawn_count"] == 1
  assert spawn_graph["team"] == DYNAMIC_AGENTS_TEAM
  assert any(node["type"] == "spawned_specialist" for node in spawn_graph["nodes"])


def test_hierarchical_topology_declares_dynamic_spawning():
  topology = hierarchical_graph_topology()
  assert topology["dynamic_agents_team"] == DYNAMIC_AGENTS_TEAM
  assert "RUN_DYNAMIC_AGENT_PLANNER" in topology["dynamic_spawning"]["actions"]
