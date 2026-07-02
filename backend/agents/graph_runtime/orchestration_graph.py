from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from ..orchestration_graph.constants import ORCHESTRATION_NODE_MAP
from ..orchestration_graph.time import now_iso
from ..orchestration_graph.trace import build_node_trace, create_orchestration_trace
from ..schema.json_safe import json_safe_value, sanitize_and_validate_for_checkpoint
from .checkpointer import build_runtime_checkpointer
from .threading import build_graph_invoke_config


def execute_langgraph_orchestration(
  *,
  intent: str,
  routing_result: dict[str, Any] | None = None,
  execute_stage: Callable[[str], None],
  emit_progress: Callable[..., None] | None = None,
  orchestration_state: dict[str, Any] | None = None,
  checkpointer_context: dict[str, Any] | None = None,
  resume_graph: bool = False,
) -> dict[str, Any]:
  trace = create_orchestration_trace(intent)
  trace["runtime"] = "worktual-langgraph-orchestration-graph"
  trace["execution_engine"] = "langgraph"
  error_holder: dict[str, Exception | None] = {"error": None}
  pipeline_state = dict(orchestration_state or {})
  pipeline_state.setdefault("intent", intent)
  pipeline_state.setdefault("routing_result", routing_result or {})

  checkpointer = None
  graph_config = None
  if isinstance(checkpointer_context, dict):
    checkpointer = build_runtime_checkpointer(
      store=checkpointer_context.get("store"),
      user=checkpointer_context.get("user"),
      agent_run_id=checkpointer_context.get("agent_run_id"),
      project_id=checkpointer_context.get("project_id"),
    )
    thread_id = str(checkpointer_context.get("thread_id") or "")
    if thread_id and ":" in thread_id:
      project_id, run_id = thread_id.split(":", 1)
      graph_config = build_graph_invoke_config(project_id=project_id, run_id=run_id)
      trace["thread_id"] = thread_id

  def record_routing_node(state: dict[str, Any]) -> dict[str, Any]:
    node = ORCHESTRATION_NODE_MAP[0]
    started_at = now_iso()
    if routing_result is not None:
      trace["nodes"].append(
        build_node_trace(
          index=1,
          node=node,
          status="completed",
          started_at=started_at,
          output=routing_result,
        )
      )
    return {**state, "completed_nodes": 1}

  def requirement_confirmation_gate_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("intent") == "needs_confirmation" and state.get("pending_confirmation"):
      resumed = interrupt(
        {
          "type": "requirement_confirmation",
          "thread_id": state.get("thread_id"),
          "brief": state.get("pending_confirmation"),
        }
      )
      return {**state, "confirmation_resume": resumed}
    return state

  def make_stage_node(index: int):
    node = ORCHESTRATION_NODE_MAP[index]

    def stage_node(state: dict[str, Any]) -> dict[str, Any]:
      node_name = node["node"]
      stage_name = node["stage"]
      if error_holder["error"] is not None:
        started_at = now_iso()
        trace["nodes"].append(
          build_node_trace(
            index=index + 1,
            node=node,
            status="skipped",
            started_at=started_at,
            error=str(error_holder["error"])[:1200],
          )
        )
        if emit_progress:
          emit_progress(
            f"graph.{node_name}.skipped",
            f"Skipped orchestration node {node_name.replace('_', ' ')} after an earlier failure",
            status="skipped",
          )
        return {**state, "completed_nodes": index + 1, "status": "skipped"}

      if emit_progress:
        emit_progress(
          f"graph.{node_name}.started",
          f"Running orchestration node {node_name.replace('_', ' ')}",
        )
      started_at = now_iso()
      try:
        execute_stage(stage_name)
      except Exception as exc:
        trace["nodes"].append(
          build_node_trace(index=index + 1, node=node, status="failed", started_at=started_at, error=str(exc))
        )
        if emit_progress:
          emit_progress(
            f"graph.{node_name}.failed",
            f"Failed orchestration node {node_name.replace('_', ' ')}",
            status="failed",
          )
        if error_holder["error"] is None:
          error_holder["error"] = exc
        return {**state, "completed_nodes": index + 1, "status": "failed"}
      trace["nodes"].append(
        build_node_trace(index=index + 1, node=node, status="completed", started_at=started_at)
      )
      if emit_progress:
        emit_progress(
          f"graph.{node_name}.completed",
          f"Completed orchestration node {node_name.replace('_', ' ')}",
          status="completed",
        )
      return {**state, "completed_nodes": index + 1, "status": "completed"}

    stage_node.__name__ = node["node"]
    return stage_node

  graph = StateGraph(dict)
  graph.add_node(ORCHESTRATION_NODE_MAP[0]["node"], record_routing_node)
  for index in range(1, len(ORCHESTRATION_NODE_MAP)):
    graph.add_node(ORCHESTRATION_NODE_MAP[index]["node"], make_stage_node(index))
  graph.add_node("requirement_confirmation_gate", requirement_confirmation_gate_node)

  graph.set_entry_point(ORCHESTRATION_NODE_MAP[0]["node"])
  graph.add_edge(ORCHESTRATION_NODE_MAP[0]["node"], ORCHESTRATION_NODE_MAP[1]["node"])
  for source, target in zip(ORCHESTRATION_NODE_MAP[1:3], ORCHESTRATION_NODE_MAP[2:4]):
    graph.add_edge(source["node"], target["node"])
  graph.add_edge(ORCHESTRATION_NODE_MAP[3]["node"], "requirement_confirmation_gate")
  graph.add_edge("requirement_confirmation_gate", ORCHESTRATION_NODE_MAP[4]["node"])
  for source, target in zip(ORCHESTRATION_NODE_MAP[4:], ORCHESTRATION_NODE_MAP[5:]):
    graph.add_edge(source["node"], target["node"])
  graph.add_edge(ORCHESTRATION_NODE_MAP[-1]["node"], END)

  if checkpointer is not None:
    app = graph.compile(checkpointer=checkpointer)
  else:
    app = graph.compile()

  if resume_graph and graph_config is not None:
    final_state = app.invoke(Command(resume=True), config=graph_config)
  else:
    safe_pipeline_state = sanitize_and_validate_for_checkpoint(pipeline_state, context="orchestration.pipeline_state")
    final_state = app.invoke(safe_pipeline_state, config=graph_config) if graph_config else app.invoke(safe_pipeline_state)

  interrupts = final_state.get("__interrupt__") if isinstance(final_state, dict) else None
  if interrupts:
    trace["status"] = "interrupted"
    interrupt_payload = interrupts[0] if isinstance(interrupts, list) and interrupts else interrupts
    trace["interrupt"] = json_safe_value(interrupt_payload)
    return trace

  if error_holder["error"] is not None:
    raise error_holder["error"]
  trace["status"] = "completed"
  return trace
