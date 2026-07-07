from __future__ import annotations

import hashlib
from typing import Any

from .adk_events import _build_adk_events
from .adk_plan import _build_adk_agent_plan
from .adk_tools import _build_adk_tool_specs
from .common import ADK_APP_NAME, ADK_RUNTIME_NAME, _create_adk_runner_metadata, _list, _text, google_adk_package_status


def _validate_adk_trace(runtime: dict[str, Any]) -> dict[str, Any]:
  plan = runtime.get("agent_plan") or {}
  agent_names = [agent.get("name") for agent in _list(plan.get("agents")) if isinstance(agent, dict)]
  return {
    "status": "valid",
    "agent_count": len(agent_names),
    "tool_count": len(_list(runtime.get("tool_specs"))),
    "event_count": len(_list(runtime.get("events"))),
  }


def build_adk_trace_from_runtime(
  *,
  user_prompt: str,
  model: str,
  routing_result: dict[str, Any],
  runtime_trace: dict[str, Any],
  a2a_runtime: dict[str, Any],
) -> dict[str, Any]:
  plan = _build_adk_agent_plan(model)
  tools = _build_adk_tool_specs()
  package = google_adk_package_status()
  prompt_digest = hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()[:12]
  branch = _text(runtime_trace.get("branch"), "unknown")
  session = {
    "app_name": ADK_APP_NAME,
    "user_id": "worktual-local-user",
    "session_id": f"adk-{branch}-{prompt_digest}",
    "new_message": {"role": "user", "parts": [{"text": user_prompt}]},
    "state": {
      "routing_result": routing_result,
      "agentic_branch": branch,
      "a2a_protocol": a2a_runtime.get("protocol"),
      "a2a_message_count": len(_list(a2a_runtime.get("messages"))),
    },
  }
  events = _build_adk_events(runtime_trace=runtime_trace, a2a_runtime=a2a_runtime)
  runtime = {
    "runtime": ADK_RUNTIME_NAME,
    "status": "completed",
    "execution_mode": "dry_run" if not package["installed"] else "runner_ready",
    "source_of_truth": bool(runtime_trace.get("tool_source_of_truth")),
    "source_of_truth_runtime": runtime_trace.get("runtime"),
    "projection_source": "live_runtime_trace" if runtime_trace.get("tool_source_of_truth") else "legacy_response_trace",
    "package": package,
    "app_name": ADK_APP_NAME,
    "model": plan["model"],
    "root_agent": plan["root_agent"],
    "agent_plan": plan,
    "tool_specs": tools,
    "session": session,
    "events": events,
    "runner": {"status": "not_created", "reason": package.get("reason", "Dry-run mode requested.")},
  }
  if package["installed"]:
    runtime["runner"] = _create_adk_runner_metadata(model=plan["model"])
  runtime["validation"] = _validate_adk_trace(runtime)
  return runtime


def execute_google_adk_runtime(
  *,
  user_prompt: str,
  model: str,
  routing_result: dict[str, Any],
  agentic_flow: dict[str, Any],
  a2a_runtime: dict[str, Any],
) -> dict[str, Any]:
  runtime = build_adk_trace_from_runtime(
    user_prompt=user_prompt,
    model=model,
    routing_result=routing_result,
    runtime_trace=agentic_flow,
    a2a_runtime=a2a_runtime,
  )
  runtime["source_of_truth"] = False
  runtime["source_of_truth_runtime"] = "worktual-real-agent-runtime-loop"
  runtime["projection_source"] = "real_agent_runtime_steps"
  runtime["execution_note"] = (
    "Google ADK metadata mirrors the real Python agent runtime. Gemini is the control and artifact model, "
    "while Python executes backend tools and validates commits."
  )
  return runtime
