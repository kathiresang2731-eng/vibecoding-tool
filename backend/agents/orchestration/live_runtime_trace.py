from __future__ import annotations

from typing import Any

from ..a2a import build_a2a_communication, build_a2a_summary
from .legacy_response_trace import build_legacy_response_trace
from .provider_utils import configured_adk_model
from .runtime_metadata import existing_agentic_runtime
from .trace_projections import (
  build_adk_trace_from_runtime,
  build_adk_trace_summary,
  build_langchain_trace_from_runtime,
  build_langchain_trace_summary,
)


def resolve_runtime_trace(response: dict[str, Any]) -> dict[str, Any]:
  live = existing_agentic_runtime(response)
  if live is not None:
    return live
  return build_legacy_response_trace(response)


def attach_live_runtime_metadata(
  response: dict[str, Any],
  *,
  user_prompt: str,
  routing_result: dict[str, Any],
) -> None:
  runtime_trace = resolve_runtime_trace(response)
  response.setdefault("multi_agent_system", {})
  response["multi_agent_system"]["agentic_runtime"] = runtime_trace

  a2a_runtime = build_a2a_communication(runtime_trace)
  google_adk_runtime = build_adk_trace_from_runtime(
    user_prompt=user_prompt,
    model=configured_adk_model(),
    routing_result=routing_result,
    runtime_trace=runtime_trace,
    a2a_runtime=a2a_runtime,
  )
  langchain_runtime = build_langchain_trace_from_runtime(
    user_prompt=user_prompt,
    routing_result=routing_result,
    runtime_trace=runtime_trace,
    a2a_runtime=a2a_runtime,
    google_adk_runtime=google_adk_runtime,
  )

  response["multi_agent_system"]["a2a_runtime"] = build_a2a_summary(a2a_runtime)
  response["multi_agent_system"]["langchain_runtime"] = build_langchain_trace_summary(langchain_runtime)
  response.setdefault("google_adk_usage", {})
  response["google_adk_usage"]["runtime"] = google_adk_runtime
  response.setdefault("agent_to_agent_communication", {})
  response["agent_to_agent_communication"]["agentic_handoffs"] = runtime_trace.get("handoffs") or []
  response["agent_to_agent_communication"]["a2a_runtime"] = a2a_runtime
  response.setdefault("proactive_thinking", {})
  response["proactive_thinking"]["langchain_runtime"] = langchain_runtime
  backend_execution = response["proactive_thinking"].setdefault("backend_execution", {})
  backend_execution["agentic_flow"] = {
    "runtime": runtime_trace.get("runtime"),
    "branch": runtime_trace.get("branch"),
    "step_count": len(runtime_trace.get("steps") or []),
    "handoff_count": len(runtime_trace.get("handoffs") or []),
    "completed_agents": [step["agent"] for step in runtime_trace.get("steps") or [] if isinstance(step, dict)],
    "source_of_truth": bool(runtime_trace.get("tool_source_of_truth")),
    "graph_topology": runtime_trace.get("graph_topology") or runtime_trace.get("runtime_graph_topology"),
  }
  backend_execution["a2a_communication"] = build_a2a_summary(a2a_runtime)
  backend_execution["google_adk_runtime"] = build_adk_trace_summary(google_adk_runtime)
  backend_execution["langchain_runtime"] = build_langchain_trace_summary(langchain_runtime)
