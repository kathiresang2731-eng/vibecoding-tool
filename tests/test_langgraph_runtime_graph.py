from __future__ import annotations

import os

import pytest
from langgraph.types import Interrupt

from backend.llm.agent_runtime.actions.dispatcher import ACTION_HANDLERS
from backend.llm.agent_runtime.loop_core import RuntimeLoopParams
from backend.llm.agent_runtime.state import initial_runtime_state
from backend.llm.graph_runtime.adapter import action_node_names
from backend.llm.graph_runtime.a2a.bus import publish_supervisor_handoff
from backend.llm.graph_runtime.edges import route_after_supervisor
from backend.llm.graph_runtime.orchestration_graph import execute_langgraph_orchestration
from backend.llm.graph_runtime.website_runtime_graph import compile_website_runtime_graph
from backend.llm.orchestration_graph.constants import ORCHESTRATION_NODE_MAP


def _params(**overrides) -> RuntimeLoopParams:
  base = {
    "project_id": "proj-graph-test",
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


def test_website_runtime_graph_registers_all_action_nodes():
  app = compile_website_runtime_graph(_params())
  node_names = set(getattr(app, "nodes", {}).keys())
  assert "supervisor" in node_names
  for action in ACTION_HANDLERS:
    assert action in node_names


def test_action_node_names_match_handlers():
  assert action_node_names() == list(ACTION_HANDLERS.keys())


def test_route_after_supervisor_routes_pending_action():
  state = {"_pending_action": "READ_PROJECT_FILES", "_graph_step_count": 1, "_graph_max_steps": 28}
  assert route_after_supervisor(state) == "READ_PROJECT_FILES"


def test_publish_supervisor_handoff_records_live_a2a_message():
  state = initial_runtime_state(
    project_id="proj-a2a",
    prompt="Build a site",
    routing_result={"intent": "website_generation"},
  )
  decision = {
    "next_action": "READ_PROJECT_FILES",
    "next_agent": "Memory Agent",
    "reason": "Need current project files before planning.",
  }
  publish_supervisor_handoff(state, decision)
  assert len(state["a2a_messages"]) == 1
  assert state["a2a_messages"][0]["to_agent"] == "Memory Agent"
  assert state["a2a_messages"][0]["intent"] == "READ_PROJECT_FILES"


def test_execute_langgraph_orchestration_runs_stages_in_order(monkeypatch):
  monkeypatch.setenv("RUNTIME_ENGINE", "langgraph")
  executed: list[str] = []

  trace = execute_langgraph_orchestration(
    intent="website_generation",
    routing_result={"intent": "website_generation"},
    execute_stage=lambda stage: executed.append(stage),
  )

  assert trace["execution_engine"] == "langgraph"
  assert trace["nodes"][0]["node"] == ORCHESTRATION_NODE_MAP[0]["node"]
  assert executed == [node["stage"] for node in ORCHESTRATION_NODE_MAP[1:]]
  assert len(trace["nodes"]) == len(ORCHESTRATION_NODE_MAP)


def test_execute_langgraph_orchestration_preserves_first_stage_failure():
  executed: list[str] = []
  root_error = RuntimeError("Scoped update timed out during the primary patch call.")

  def execute_stage(stage: str) -> None:
    executed.append(stage)
    if stage == "orchestration_flow":
      raise root_error

  with pytest.raises(RuntimeError, match="primary patch call"):
    execute_langgraph_orchestration(
      intent="website_update",
      routing_result={"intent": "website_update"},
      execute_stage=execute_stage,
    )

  assert executed == [
    "multi_agent_system",
    "gemini_tool_calling_setup",
    "google_adk_usage",
    "orchestration_flow",
  ]


def test_execute_langgraph_orchestration_interrupt_trace_is_json_safe(monkeypatch):
  monkeypatch.setenv("RUNTIME_ENGINE", "langgraph")
  interrupt_payload = Interrupt(
    {
      "type": "requirement_confirmation",
      "thread_id": "project-1:run-1",
      "brief": {"summary": "Confirm storefront generation", "status": "pending"},
    }
  )

  class InterruptingGraph:
    def invoke(self, _state, config=None):
      return {"__interrupt__": [interrupt_payload]}

  monkeypatch.setattr(
    "backend.llm.graph_runtime.orchestration_graph.StateGraph.compile",
    lambda self, checkpointer=None: InterruptingGraph(),
  )

  trace = execute_langgraph_orchestration(
    intent="needs_confirmation",
    routing_result={"intent": "needs_confirmation"},
    orchestration_state={
      "intent": "needs_confirmation",
      "pending_confirmation": {"summary": "Confirm storefront generation", "status": "pending"},
      "thread_id": "project-1:run-1",
    },
    execute_stage=lambda _stage: None,
  )

  assert trace["status"] == "interrupted"
  assert trace["interrupt"]["type"] == "langgraph_interrupt"
  assert trace["interrupt"]["value"]["type"] == "requirement_confirmation"
  import json

  json.dumps(trace)


def test_runtime_engine_defaults_to_langgraph_at_high_parity(monkeypatch):
  monkeypatch.delenv("RUNTIME_ENGINE", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  from backend.llm.runtime_config import runtime_engine

  assert runtime_engine() == "langgraph"


def test_runtime_engine_defaults_to_langgraph_without_parity_override(monkeypatch):
  monkeypatch.delenv("RUNTIME_ENGINE", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "0")
  from backend.llm.runtime_config import runtime_engine

  assert runtime_engine() == "langgraph"


def test_runtime_engine_keeps_explicit_legacy_override(monkeypatch):
  monkeypatch.setenv("RUNTIME_ENGINE", "legacy_python_loop")
  from backend.llm.runtime_config import runtime_engine

  assert runtime_engine() == "legacy_python_loop"
