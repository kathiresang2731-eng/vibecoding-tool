from __future__ import annotations

from typing import Any

from backend.agents.a2a import build_a2a_communication, build_a2a_summary
from ..provider_utils import configured_adk_model
from ..trace_projections import (
  build_adk_trace_from_runtime,
  build_adk_trace_summary,
  build_langchain_trace_from_runtime,
  build_langchain_trace_summary,
)
from backend.agents.agentic_flow.artifact import build_artifact_steps
from backend.agents.agentic_flow.constants import AGENT_ROSTER, AGENTIC_RUNTIME_NAME
from backend.agents.agentic_flow.conversation import build_conversation_steps
from backend.agents.agentic_flow.handoffs import build_handoffs
from backend.agents.agentic_flow.steps import agent_step
from backend.agents.agentic_flow.values import list_value, object_value, text_value
from .state import existing_agentic_runtime


def build_legacy_response_trace(response: dict[str, Any]) -> dict[str, Any]:
  """Synthesize a response trace for legacy one-shot generation paths without a live runtime loop."""
  multi_agent = response.get("multi_agent_system") if isinstance(response, dict) else {}
  orchestration = response.get("orchestration_flow") if isinstance(response, dict) else {}
  proactive = response.get("proactive_thinking") if isinstance(response, dict) else {}
  if not isinstance(multi_agent, dict) or not isinstance(orchestration, dict):
    raise ValueError("Legacy response trace requires a normalized generation response.")

  intent = text_value(multi_agent.get("intent"), "unknown")
  routing_result = object_value(multi_agent.get("routing_result"))
  generated_website = object_value(orchestration.get("generated_website"))
  conversation_response = object_value(multi_agent.get("conversation_response"))
  branch = intent if intent in {"simple_code", "website_generation", "website_update"} else "conversation"

  steps: list[dict[str, Any]] = [
    agent_step(
      index=1,
      agent="Intent Router Agent",
      action="route_user_turn",
      input_payload={"prompt": multi_agent.get("shared_state", {}).get("prompt")},
      output_payload=routing_result,
    )
  ]

  if branch == "conversation":
    steps.extend(
      build_conversation_steps(
        intent=intent,
        routing_result=routing_result,
        conversation_response=conversation_response,
        start_index=2,
      )
    )
  else:
    steps.extend(
      build_artifact_steps(
        intent=intent,
        routing_result=routing_result,
        generated_website=generated_website,
        proactive=object_value(proactive),
        start_index=2,
      )
    )

  return {
    "runtime": AGENTIC_RUNTIME_NAME,
    "status": "completed",
    "branch": branch,
    "tool_source_of_truth": False,
    "source": "legacy_response_trace",
    "agents": AGENT_ROSTER,
    "steps": steps,
    "handoffs": build_handoffs(steps),
    "final_output": {
      "intent": intent,
      "message": conversation_response.get("message"),
      "file_count": len(list_value(generated_website.get("files"))) if branch in {"simple_code", "website_generation", "website_update"} else 0,
    },
  }


def resolve_runtime_trace(response: dict[str, Any]) -> dict[str, Any]:
  live = existing_agentic_runtime(response)
  if live is not None:
    if (
      (str(live.get("status") or "").lower() == "failed" or bool(live.get("no_code_changes")))
      and not list_value(live.get("steps"))
    ):
      live = {
        **live,
        "steps": [
          agent_step(
            index=1,
            agent="Update Runtime",
            action="update_failed_before_commit",
            input_payload={"branch": live.get("branch") or live.get("operation") or "website_update"},
            output_payload={
              "status": live.get("status") or "failed",
              "no_code_changes": bool(live.get("no_code_changes")),
              "message": live.get("output_text") or "Website update failed before producing file edits.",
              "changed_paths": live.get("changed_paths") or [],
            },
          )
        ],
      }
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
