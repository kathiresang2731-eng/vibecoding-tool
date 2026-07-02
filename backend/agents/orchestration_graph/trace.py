from __future__ import annotations

from typing import Any

from .constants import ORCHESTRATION_NODE_MAP
from .time import now_iso


def create_orchestration_trace(intent: str) -> dict[str, Any]:
  branch = intent if intent in {"website_generation", "website_update"} else "conversation"
  return {
    "runtime": "worktual-python-orchestration-graph",
    "entrypoint": "route_user_intent",
    "intent": intent,
    "branch": branch,
    "nodes": [],
    "edges": build_edges(),
  }


def build_edges() -> list[dict[str, str]]:
  edges = []
  for source, target in zip(ORCHESTRATION_NODE_MAP, ORCHESTRATION_NODE_MAP[1:]):
    edges.append({"from": source["node"], "to": target["node"]})
  return edges


def build_node_trace(
  *,
  index: int,
  node: dict[str, str],
  status: str,
  started_at: str,
  error: str | None = None,
  output: dict[str, Any] | None = None,
) -> dict[str, Any]:
  payload: dict[str, Any] = {
    "index": index,
    "node": node["node"],
    "stage": node["stage"],
    "description": node["description"],
    "status": status,
    "started_at": started_at,
    "completed_at": now_iso(),
  }
  if error:
    payload["error"] = error
  if output is not None:
    payload["output"] = output
  return payload
