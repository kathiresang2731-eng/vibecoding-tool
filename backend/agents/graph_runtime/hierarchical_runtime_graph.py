from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Command

from ..agent_runtime.errors import AgentRuntimeLoopError
from ..agent_runtime.loop_core import RuntimeLoopParams, finalize_runtime_loop_result, prepare_runtime_loop_state
from ..agent_runtime.tooling import restore_previous_project_files
from ..agent_runtime.values import object_value
from ..schema.json_safe import sanitize_and_validate_for_checkpoint
from .checkpointer import build_runtime_checkpointer
from .hierarchical_edges import route_after_chief, route_after_team
from .hierarchical_teams import CHIEF_SUPERVISOR, DYNAMIC_AGENTS_TEAM, TEAM_IDS
from .nodes.chief_supervisor import build_chief_supervisor_node
from .nodes.dynamic_team import build_dynamic_team_node
from .nodes.team import build_team_node
from .threading import build_graph_invoke_config


def compile_hierarchical_runtime_graph(params: RuntimeLoopParams, *, checkpointer: Any | None = None) -> Any:
  graph = StateGraph(dict)
  graph.add_node(CHIEF_SUPERVISOR, build_chief_supervisor_node(params))

  team_routes: dict[str, str] = {}
  for team_id in TEAM_IDS:
    if team_id == DYNAMIC_AGENTS_TEAM:
      graph.add_node(team_id, build_dynamic_team_node(params))
    else:
      graph.add_node(team_id, build_team_node(team_id, params))
    graph.add_edge(team_id, CHIEF_SUPERVISOR)
    team_routes[team_id] = team_id

  graph.add_conditional_edges(
    CHIEF_SUPERVISOR,
    route_after_chief,
    {**team_routes, CHIEF_SUPERVISOR: CHIEF_SUPERVISOR, END: END},
  )
  for team_id in TEAM_IDS:
    graph.add_conditional_edges(team_id, route_after_team, {CHIEF_SUPERVISOR: CHIEF_SUPERVISOR})

  graph.set_entry_point(CHIEF_SUPERVISOR)
  if checkpointer is not None:
    return graph.compile(checkpointer=checkpointer)
  return graph.compile()


def hierarchical_graph_topology() -> dict[str, Any]:
  return {
    "topology": "hierarchical",
    "chief_supervisor": CHIEF_SUPERVISOR,
    "teams": list(TEAM_IDS),
    "dynamic_agents_team": DYNAMIC_AGENTS_TEAM,
    "execution_model": "chief_routes_to_teams_with_intra_team_batching",
    "dynamic_spawning": {
      "team": DYNAMIC_AGENTS_TEAM,
      "actions": [
        "RUN_DYNAMIC_AGENT_PLANNER",
        "RUN_DYNAMIC_SPECIALISTS",
        "RUN_DYNAMIC_PATCH_INTEGRATOR",
      ],
      "specialist_engine": "langgraph_send",
    },
    "parallelism": "thread_pool_for_bootstrap_reviews_and_dynamic_specialists",
  }


def _resolve_graph_config(params: RuntimeLoopParams) -> dict[str, Any] | None:
  if not params.graph_thread_id:
    return None
  project_id, run_id = params.graph_thread_id.split(":", 1)
  return build_graph_invoke_config(project_id=project_id, run_id=run_id)


def execute_hierarchical_runtime_graph(params: RuntimeLoopParams) -> dict[str, Any]:
  checkpointer = None
  if params.graph_thread_id:
    checkpointer = build_runtime_checkpointer(
      store=getattr(params.tool_context, "store", None),
      user=params.user,
      agent_run_id=params.agent_run_id,
      project_id=params.project_id,
    )
  app = compile_hierarchical_runtime_graph(params, checkpointer=checkpointer)
  config = _resolve_graph_config(params)
  if params.resume_graph and config is not None:
    final_state = app.invoke(Command(resume=True), config=config)
  else:
    initial_state = prepare_runtime_loop_state(params)
    initial_state["_graph_step_count"] = 0
    initial_state["_graph_max_steps"] = params.max_steps
    initial_state["runtime_graph_topology"] = hierarchical_graph_topology()
    if params.graph_thread_id:
      initial_state["graph_thread_id"] = params.graph_thread_id
    safe_initial_state = sanitize_and_validate_for_checkpoint(initial_state, context="hierarchical_runtime.initial_state")
    final_state = app.invoke(safe_initial_state, config=config) if config else app.invoke(safe_initial_state)

  if not final_state.get("completed"):
    if final_state.get("awaiting_patch_approval"):
      return finalize_runtime_loop_result(final_state)
    restore_previous_project_files(
      final_state,
      tool_executor=params.tool_executor,
      tool_context=params.tool_context,
      user=params.user,
      project_id=params.project_id,
      read_result=object_value(final_state.get("read_result")),
    )
    raise AgentRuntimeLoopError("Hierarchical LangGraph runtime exhausted its step budget before DONE; restored previous project files.")

  result = finalize_runtime_loop_result(final_state)
  runtime = result.get("runtime")
  if isinstance(runtime, dict):
    runtime["graph_topology"] = hierarchical_graph_topology()
  return result
