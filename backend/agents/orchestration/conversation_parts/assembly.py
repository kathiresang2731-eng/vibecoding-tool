from __future__ import annotations

from typing import Any

from backend.debug_trace import trace_print
from backend.agents.schema import sanitize_generation_response
from backend.agents.orchestration.state import GenerationPipelineState
from .assembly_parts import build_conversation_agent_to_agent_communication
from .assembly_parts import build_conversation_gemini_tool_calling_setup
from .assembly_parts import build_conversation_google_adk_usage
from .assembly_parts import build_conversation_multi_agent_system
from .assembly_parts import build_conversation_orchestration_flow
from .assembly_parts import build_conversation_proactive_thinking


def build_conversation_generation_response(
  state: GenerationPipelineState,
  conversation_response: dict[str, Any],
) -> dict[str, Any]:
  trace_print(
    "ENTER",
    file=__file__,
    class_name="-",
    function="build_conversation_generation_response",
    intent=state.intent,
    next_tool=state.routing_result.get("next_tool"),
  )
  next_tool_name = state.routing_result["next_tool"]

  response = sanitize_generation_response(
    {
      "multi_agent_system": build_conversation_multi_agent_system(state, conversation_response),
      "gemini_tool_calling_setup": build_conversation_gemini_tool_calling_setup(state, conversation_response, next_tool_name),
      "google_adk_usage": build_conversation_google_adk_usage(state),
      "orchestration_flow": build_conversation_orchestration_flow(state, conversation_response),
      "agent_to_agent_communication": build_conversation_agent_to_agent_communication(state, conversation_response),
      "proactive_thinking": build_conversation_proactive_thinking(state, conversation_response),
    }
  )
  trace_print(
    "EXIT",
    file=__file__,
    class_name="-",
    function="build_conversation_generation_response",
    intent=state.intent,
    next_tool=next_tool_name,
  )
  return response
