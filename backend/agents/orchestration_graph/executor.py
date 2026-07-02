from __future__ import annotations

from typing import Any, Callable

from .constants import ORCHESTRATION_NODE_MAP
from .time import now_iso
from .trace import build_node_trace, create_orchestration_trace


def execute_orchestration_stage_graph(
  *,
  intent: str,
  routing_result: dict[str, Any] | None = None,
  execute_stage: Callable[[str], None],
  emit_progress: Callable[..., None] | None = None,
) -> dict[str, Any]:
  trace = create_orchestration_trace(intent)
  if routing_result is not None:
    trace["nodes"].append(
      build_node_trace(
        index=1,
        node=ORCHESTRATION_NODE_MAP[0],
        status="completed",
        started_at=now_iso(),
        output=routing_result,
      )
    )

  stage_nodes = ORCHESTRATION_NODE_MAP[1:]
  for index, node in enumerate(stage_nodes, start=2):
    node_name = node["node"]
    stage_name = node["stage"]
    if emit_progress:
      emit_progress(
        f"graph.{node_name}.started",
        f"Running orchestration node {node_name.replace('_', ' ')}",
      )
    started_at = now_iso()
    try:
      execute_stage(stage_name)
      status = "completed"
      error = None
    except Exception as exc:
      status = "failed"
      error = str(exc)
      trace["nodes"].append(
        build_node_trace(index=index, node=node, status=status, started_at=started_at, error=error)
      )
      if emit_progress:
        emit_progress(
          f"graph.{node_name}.failed",
          f"Failed orchestration node {node_name.replace('_', ' ')}",
          status="failed",
        )
      raise

    trace["nodes"].append(build_node_trace(index=index, node=node, status=status, started_at=started_at))
    if emit_progress:
      emit_progress(
        f"graph.{node_name}.completed",
        f"Completed orchestration node {node_name.replace('_', ' ')}",
        status="completed",
      )

  return trace
