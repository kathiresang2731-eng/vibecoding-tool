from __future__ import annotations

import msgpack

from backend.llm.graph_runtime import dynamic_specialists_graph
from backend.llm.graph_runtime.dynamic_specialists_graph import execute_parallel_specialist_group
from backend.llm.graph_runtime.threading import build_graph_invoke_config, build_runtime_thread_id, parse_runtime_thread_id


class FakeRegistry:
  agents = {}


class FakeProvider:
  def generate_json(self, *_args, **_kwargs):
    return {
      "summary": "Specialist output",
      "recommendations": ["Use a hero section"],
      "requirements": ["Include CTA"],
      "risks": ["Validate preview"],
      "candidate_changes": [],
    }


def test_parallel_specialist_group_uses_langgraph_send():
  workflow_plan = {
    "tasks": [
      {"id": "content_strategy", "runtime_action": "RUN_DYNAMIC_SPECIALISTS", "required_capability": "content_strategy"},
      {"id": "component_plan", "runtime_action": "RUN_DYNAMIC_SPECIALISTS", "required_capability": "component_plan"},
    ],
    "assignments": [
      {"task_id": "content_strategy", "agent_id": "agent-1", "agent_name": "Content Agent"},
      {"task_id": "component_plan", "agent_id": "agent-2", "agent_name": "Component Agent"},
    ],
  }
  results = execute_parallel_specialist_group(
    provider=FakeProvider(),
    workflow_plan=workflow_plan,
    group_task_ids=["content_strategy", "component_plan"],
    prompt="Build a SaaS landing page",
    brief={"summary": "SaaS landing page"},
    plan={"sections": ["hero"]},
    registry=FakeRegistry(),
    execute_tool=None,
  )
  assert set(results.keys()) == {"content_strategy", "component_plan"}
  assert all(isinstance(item, dict) for item in results.values())


def test_parallel_specialist_group_keeps_runtime_objects_out_of_graph_state(monkeypatch):
  class MsgpackHostileProvider:
    def generate_json(self, *_args, **_kwargs):
      return {"summary": "Specialist output", "candidate_changes": []}

  provider = MsgpackHostileProvider()
  workflow_plan = {
    "tasks": [
      {"id": "content_strategy", "runtime_action": "RUN_DYNAMIC_SPECIALISTS", "required_capability": "content_strategy"},
    ],
    "assignments": [
      {"task_id": "content_strategy", "agent_id": "agent-1", "agent_name": "Content Agent"},
    ],
  }

  class SerializableStateProbe:
    def invoke(self, state):
      assert "provider" not in state
      assert "registry" not in state
      assert "execute_tool" not in state
      msgpack.packb(state)
      return {"merged_results": {"content_strategy": {"status": "completed"}}}

  monkeypatch.setattr(
    dynamic_specialists_graph.StateGraph,
    "compile",
    lambda self: SerializableStateProbe(),
  )

  results = execute_parallel_specialist_group(
    provider=provider,
    workflow_plan=workflow_plan,
    group_task_ids=["content_strategy"],
    prompt="Build a SaaS landing page",
    brief={"summary": "SaaS landing page"},
    plan={"sections": ["hero"]},
    registry=FakeRegistry(),
    execute_tool=lambda _name, _arguments: {"status": "ok"},
  )

  assert results == {"content_strategy": {"status": "completed"}}


def test_build_runtime_thread_id_and_parse():
  thread_id = build_runtime_thread_id(project_id="project-1", run_id="run-abc")
  assert thread_id == "project-1:run-abc"
  project_id, run_id = parse_runtime_thread_id(thread_id)
  assert project_id == "project-1"
  assert run_id == "run-abc"
  assert build_graph_invoke_config(project_id="project-1", run_id="run-abc") == {
    "configurable": {"thread_id": "project-1:run-abc"}
  }


def test_postgres_mirror_checkpointer_is_valid_langgraph_saver():
  from langgraph.checkpoint.base import BaseCheckpointSaver
  from langgraph.graph import END, StateGraph

  from backend.llm.graph_runtime.checkpointer import PostgresMirrorCheckpointer

  saver = PostgresMirrorCheckpointer(
    store=None,
    user=None,
    agent_run_id="run-1",
    project_id="project-1",
  )
  assert isinstance(saver, BaseCheckpointSaver)

  graph = StateGraph(dict)
  graph.add_node("noop", lambda state: state)
  graph.set_entry_point("noop")
  graph.add_edge("noop", END)
  app = graph.compile(checkpointer=saver)
  app.invoke({}, config={"configurable": {"thread_id": "project-1:run-1"}})
