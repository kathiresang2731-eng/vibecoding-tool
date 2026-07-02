from __future__ import annotations

from typing import Any

from ..agentic_flow.artifact import build_artifact_steps
from ..agentic_flow.constants import AGENT_ROSTER, AGENTIC_RUNTIME_NAME
from ..agentic_flow.conversation import build_conversation_steps
from ..agentic_flow.handoffs import build_handoffs
from ..agentic_flow.steps import agent_step
from ..agentic_flow.values import list_value, object_value, text_value


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
