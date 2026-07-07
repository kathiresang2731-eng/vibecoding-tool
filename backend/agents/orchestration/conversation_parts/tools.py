from __future__ import annotations

from typing import Any

from backend.agents.orchestration.state import GenerationPipelineState


def build_selected_tool_arguments(state: GenerationPipelineState, tool_name: str) -> dict[str, Any]:
  if tool_name == "handle_greeting":
    return {
      "message": state.user_prompt,
      "conversation_context": "website_builder_chat",
    }
  if tool_name == "confirm_execution_brief":
    return {
      "message": state.user_prompt,
      "execution_brief": (state.conversation_response_override or {}).get("confirmation", {}),
    }
  if tool_name == "summarize_current_project":
    return {
      "message": state.user_prompt,
      "conversation_context": "current_project_summary",
      "project_context": state.routing_result.get("project_context", {}),
    }
  if tool_name in {"answer_question", "answer_general_query", "search_web"}:
    return {
      "message": state.user_prompt,
      "conversation_context": "read_only_assistant_turn",
      "web_search": tool_name == "search_web",
    }

  return {
    "message": state.user_prompt,
    "missing_fields": ["website type", "brand name", "sections", "style", "features"],
  }
