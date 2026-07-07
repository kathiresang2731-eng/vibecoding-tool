from __future__ import annotations

import hashlib
from typing import Any

from backend.agents.runtime_config import agentic_parity_target, runtime_engine
from .common import (
  LANGCHAIN_RUNTIME_NAME,
  LANGCHAIN_STAGE_ORDER,
  LANGCHAIN_SYSTEM_PROMPT,
  AGENT_STAGE_MAP,
  _list,
  _obj,
  _text,
  build_thread_config,
  package_status_pair,
  google_adk_package_status,
  LangChainRuntimeError,
)


def build_langchain_trace_from_runtime(
  *,
  user_prompt: str,
  routing_result: dict[str, Any],
  runtime_trace: dict[str, Any],
  a2a_runtime: dict[str, Any],
  google_adk_runtime: dict[str, Any],
) -> dict[str, Any]:
  packages = package_status_pair()
  graph_ready = packages["langchain"]["installed"] and packages["langgraph"]["installed"]
  executing = runtime_engine() == "langgraph" and agentic_parity_target() >= 90 and bool(runtime_trace.get("tool_source_of_truth"))
  if executing and graph_ready:
    execution_mode = "executing"
  elif graph_ready:
    execution_mode = "graph_ready"
  else:
    execution_mode = "dry_run"

  branch = _text(runtime_trace.get("branch"), "unknown")
  digest = hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()[:12]
  thread_id = f"langgraph-{branch}-{digest}"
  final_output = _obj(runtime_trace.get("final_output"))
  memory_line = f"Latest branch: {branch}."
  if isinstance(final_output.get("file_count"), int):
    memory_line = f"{memory_line} File count: {final_output['file_count']}."
  messages = [
    {"role": "system", "content": LANGCHAIN_SYSTEM_PROMPT},
    {"role": "system", "content": f"Relevant persisted memory:\n[runtime/summary/latest_agentic_output] {memory_line}"},
    {"role": "user", "content": user_prompt.strip()},
  ]
  nodes = _build_langgraph_nodes(runtime_trace=runtime_trace, a2a_runtime=a2a_runtime)
  runtime = {
    "runtime": LANGCHAIN_RUNTIME_NAME,
    "status": "completed",
    "execution_mode": execution_mode,
    "source_of_truth": executing and graph_ready,
    "source_of_truth_runtime": runtime_trace.get("runtime"),
    "projection_source": "live_runtime_trace" if runtime_trace.get("tool_source_of_truth") else "legacy_response_trace",
    "packages": packages,
    "thread_config": {"configurable": {"thread_id": thread_id}},
    "stage_order": list(LANGCHAIN_STAGE_ORDER),
    "messages": messages,
    "state": {
      "routing_result": routing_result,
      "branch": branch,
      "a2a_protocol": a2a_runtime.get("protocol"),
      "google_adk_execution_mode": google_adk_runtime.get("execution_mode"),
      "final_output": final_output,
      "graph_topology": runtime_trace.get("graph_topology") or runtime_trace.get("runtime_graph_topology"),
    },
    "graph": {
      "entrypoint": "router",
      "terminal": "memory_writer",
      "nodes": nodes,
      "edges": [{"from": source, "to": target} for source, target in zip(LANGCHAIN_STAGE_ORDER, LANGCHAIN_STAGE_ORDER[1:])],
      "compiled": graph_ready,
    },
  }
  runtime["validation"] = _validate_langchain_trace(runtime)
  return runtime


def build_langchain_trace_summary(runtime: dict[str, Any]) -> dict[str, Any]:
  return {
    "runtime": runtime["runtime"],
    "status": runtime["status"],
    "execution_mode": runtime["execution_mode"],
    "source_of_truth": runtime.get("source_of_truth") is True,
    "source_of_truth_runtime": runtime.get("source_of_truth_runtime"),
    "thread_id": runtime["thread_config"]["configurable"]["thread_id"],
    "message_count": len(runtime["messages"]),
    "node_count": len(runtime["graph"]["nodes"]),
    "validation_status": runtime["validation"]["status"],
  }


def format_memory_context(memory_items: list[dict[str, Any]]) -> str:
  lines: list[str] = []
  for item in memory_items:
    if not isinstance(item, dict):
      continue
    namespace = _text(item.get("namespace"), "memory")
    key = _text(item.get("key"), "item")
    kind = _text(item.get("kind"), "summary")
    content = _text(item.get("content"), "")
    if not content:
      continue
    lines.append(f"[{namespace}/{kind}/{key}] {content}")
  return "\n".join(lines)


def _build_langgraph_nodes(*, runtime_trace: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  steps = _list(runtime_trace.get("steps"))
  messages = _list(a2a_runtime.get("messages"))
  incoming_by_agent = {message.get("to_agent"): message for message in messages if isinstance(message, dict)}
  outgoing_by_agent = {message.get("from_agent"): message for message in messages if isinstance(message, dict)}
  nodes: list[dict[str, Any]] = []
  for step in steps:
    if not isinstance(step, dict):
      continue
    agent = _text(step.get("agent"), "Unknown Agent")
    stage = AGENT_STAGE_MAP.get(agent, "supervisor")
    action = _text(step.get("action"), "agent_step")
    if agent == "Memory Agent" and any(term in action for term in ("read", "load")):
      stage = "memory"
    nodes.append(
      {
        "node": stage,
        "agent": agent,
        "action": action,
        "status": _text(step.get("status"), "completed"),
        "input_keys": sorted(_obj(step.get("input")).keys()),
        "output_keys": sorted(_obj(step.get("output")).keys()),
        "tool_calls": _list(step.get("tool_calls")),
        "a2a_received_message_id": _obj(incoming_by_agent.get(agent)).get("message_id"),
        "a2a_sent_message_id": _obj(outgoing_by_agent.get(agent)).get("message_id"),
      }
    )
  return nodes


def _validate_langchain_trace(runtime: dict[str, Any]) -> dict[str, Any]:
  graph = _obj(runtime.get("graph"))
  nodes = _list(graph.get("nodes"))
  return {
    "status": "valid",
    "message_count": len(_list(runtime.get("messages"))),
    "node_count": len(nodes),
    "edge_count": len(_list(graph.get("edges"))),
  }


def build_langchain_messages(
  *,
  system_prompt: str,
  user_prompt: str,
  memory_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
  messages = [{"role": "system", "content": system_prompt.strip()}]
  memory_context = format_memory_context(memory_items or [])
  if memory_context:
    messages.append({"role": "system", "content": f"Relevant persisted memory:\n{memory_context}"})
  messages.append({"role": "user", "content": user_prompt.strip()})
  return messages


def build_langgraph_node_projection(*, agentic_flow: dict[str, Any], a2a_runtime: dict[str, Any]) -> list[dict[str, Any]]:
  return _build_langgraph_nodes(runtime_trace=agentic_flow, a2a_runtime=a2a_runtime)


def langchain_package_status() -> dict[str, dict[str, Any]]:
  return package_status_pair()


def execute_langchain_runtime(
  *,
  user_prompt: str,
  routing_result: dict[str, Any],
  agentic_flow: dict[str, Any],
  a2a_runtime: dict[str, Any],
  google_adk_runtime: dict[str, Any],
) -> dict[str, Any]:
  runtime = build_langchain_trace_from_runtime(
    user_prompt=user_prompt,
    routing_result=routing_result,
    runtime_trace=agentic_flow,
    a2a_runtime=a2a_runtime,
    google_adk_runtime=google_adk_runtime,
  )
  runtime["source_of_truth"] = False
  runtime["source_of_truth_runtime"] = "worktual-real-agent-runtime-loop"
  runtime["projection_source"] = "real_agent_runtime_steps"
  return runtime
