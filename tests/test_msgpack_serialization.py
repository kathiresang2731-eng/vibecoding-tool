from __future__ import annotations

import msgpack
import pytest
from langgraph.graph import END, StateGraph

from backend.agents.dynamic_agenting.registry import AgentRegistry
from backend.agents.graph_runtime.checkpointer import PostgresMirrorCheckpointer, SanitizingMemorySaver
from backend.agents.schema.json_safe import (
  ensure_msgpack_serializable,
  sanitize_and_validate_for_checkpoint,
  sanitize_graph_node_state,
)


def test_ensure_msgpack_serializable_converts_agent_registry():
  registry = AgentRegistry(owner_user_id="user-1")
  payload = {"dynamic_agent_registry": registry, "prompt": "Build a site"}

  safe = ensure_msgpack_serializable(payload, context="test.registry")
  msgpack.packb(safe, use_bin_type=True, strict_types=True)

  assert safe["prompt"] == "Build a site"
  assert isinstance(safe["dynamic_agent_registry"], dict)
  assert "agent_count" in safe["dynamic_agent_registry"]


def test_ensure_msgpack_serializable_drops_runtime_only_registry_key():
  registry = AgentRegistry(owner_user_id="user-1")
  payload = {"registry": registry, "prompt": "Build a site"}

  safe = ensure_msgpack_serializable(payload, context="test.registry")
  msgpack.packb(safe, use_bin_type=True, strict_types=True)

  assert "registry" not in safe
  assert safe["prompt"] == "Build a site"


def test_sanitize_graph_node_state_strips_runtime_registry_key():
  registry = AgentRegistry(owner_user_id="user-1")
  state = {"project_id": "p-1", "registry": registry, "operation": "generate"}

  safe = sanitize_graph_node_state(state)
  msgpack.packb(safe, use_bin_type=True, strict_types=True)

  assert "registry" not in safe
  assert safe["project_id"] == "p-1"


@pytest.mark.parametrize("saver_factory", [SanitizingMemorySaver, lambda: PostgresMirrorCheckpointer(store=None, user=None)])
def test_sanitizing_checkpointer_survives_agent_registry_in_graph_state(saver_factory):
  registry = AgentRegistry(owner_user_id="user-1")

  def node(state):
    updated = dict(state)
    updated["registry"] = registry
    updated["_dynamic_agent_registry"] = registry
    return updated

  graph = StateGraph(dict)
  graph.add_node("n", node)
  graph.set_entry_point("n")
  graph.add_edge("n", END)
  app = graph.compile(checkpointer=saver_factory())
  result = app.invoke({}, config={"configurable": {"thread_id": "project-1:run-1"}})

  assert isinstance(result, dict)
  msgpack.packb(sanitize_and_validate_for_checkpoint(result), use_bin_type=True, strict_types=True)
