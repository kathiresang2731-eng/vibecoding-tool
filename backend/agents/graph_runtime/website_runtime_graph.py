from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from ..agent_runtime.actions.dispatcher import ACTION_HANDLERS
from ..agent_runtime.errors import AgentRuntimeLoopError
from ..agent_runtime.loop_core import RuntimeLoopParams, finalize_runtime_loop_result, prepare_runtime_loop_state
from ..agent_runtime.tooling import restore_previous_project_files
from ..agent_runtime.values import object_value
from ..schema.json_safe import sanitize_and_validate_for_checkpoint
from .adapter import make_action_node
from .checkpointer import build_runtime_checkpointer
from .edges import route_after_action, route_after_supervisor
from .nodes.supervisor import build_supervisor_node
from .threading import build_graph_invoke_config


def compile_website_runtime_graph(params: RuntimeLoopParams, *, checkpointer: Any | None = None) -> Any:
  graph = StateGraph(dict)
  supervisor_node = build_supervisor_node(params)
  graph.add_node("supervisor", supervisor_node)

  action_routes: dict[str, str] = {}
  for action in ACTION_HANDLERS:
    graph.add_node(action, make_action_node(action, params))
    graph.add_edge(action, "supervisor")
    action_routes[action] = action

  graph.add_conditional_edges(
    "supervisor",
    route_after_supervisor,
    {**action_routes, "supervisor": "supervisor", END: END},
  )
  for action in ACTION_HANDLERS:
    graph.add_conditional_edges(action, route_after_action, {"supervisor": "supervisor"})

  graph.set_entry_point("supervisor")
  if checkpointer is not None:
    return graph.compile(checkpointer=checkpointer)
  return graph.compile()


def _resolve_graph_config(params: RuntimeLoopParams) -> dict[str, Any] | None:
  if not params.graph_thread_id:
    return None
  project_id, run_id = params.graph_thread_id.split(":", 1)
  return build_graph_invoke_config(project_id=project_id, run_id=run_id)


def execute_website_runtime_graph(params: RuntimeLoopParams) -> dict[str, Any]:
  checkpointer = None
  if params.graph_thread_id:
    checkpointer = build_runtime_checkpointer(
      store=getattr(params.tool_context, "store", None),
      user=params.user,
      agent_run_id=params.agent_run_id,
      project_id=params.project_id,
    )
  app = compile_website_runtime_graph(params, checkpointer=checkpointer)
  config = _resolve_graph_config(params)
  if params.resume_graph and config is not None:
    final_state = app.invoke(Command(resume=True), config=config)
  else:
    initial_state = prepare_runtime_loop_state(params)
    initial_state["_graph_step_count"] = 0
    initial_state["_graph_max_steps"] = params.max_steps
    if params.graph_thread_id:
      initial_state["graph_thread_id"] = params.graph_thread_id
    safe_initial_state = sanitize_and_validate_for_checkpoint(initial_state, context="website_runtime.initial_state")
    final_state = app.invoke(safe_initial_state, config=config) if config else app.invoke(safe_initial_state)

  if not final_state.get("completed"):
    if final_state.get("awaiting_patch_approval"):
      generated_website = object_value(final_state.get("generated_website"))
      if not generated_website:
        candidate_files = [
          {"path": str(item.get("path") or ""), "content": str(item.get("content") or item.get("code") or "")}
          for item in list(final_state.get("candidate_files") or [])
          if isinstance(item, dict) and str(item.get("path") or "").strip()
        ]
        generated_website = {
          "title": "Proposed patch",
          "subheadline": str(final_state.get("prompt") or ""),
          "files": candidate_files,
        }
      return finalize_runtime_loop_result(final_state)
    restore_previous_project_files(
      final_state,
      tool_executor=params.tool_executor,
      tool_context=params.tool_context,
      user=params.user,
      project_id=params.project_id,
      read_result=object_value(final_state.get("read_result")),
    )
    raise AgentRuntimeLoopError("LangGraph runtime exhausted its step budget before DONE; restored previous project files.")

  return finalize_runtime_loop_result(final_state)
