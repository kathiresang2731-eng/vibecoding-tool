from __future__ import annotations

from ..runtime_config import runtime_graph_topology
from ..agent_runtime.loop_core import RuntimeLoopParams
from .hierarchical_runtime_graph import execute_hierarchical_runtime_graph
from .website_runtime_graph import execute_website_runtime_graph


def execute_langgraph_agent_runtime_loop(params: RuntimeLoopParams) -> dict[str, Any]:
  if runtime_graph_topology() == "hierarchical":
    return execute_hierarchical_runtime_graph(params)
  return execute_website_runtime_graph(params)
