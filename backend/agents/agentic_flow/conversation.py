from __future__ import annotations

from typing import Any

from .steps import agent_step
from .values import text_value


def build_conversation_steps(
  *,
  intent: str,
  routing_result: dict[str, Any],
  conversation_response: dict[str, Any],
  start_index: int,
) -> list[dict[str, Any]]:
  conversation_agent = "Intent Router Agent" if str(intent or "").strip().lower() == "greeting" else "Conversation Agent"
  conversation_action = (
    "handle_greeting_without_file_generation"
    if str(intent or "").strip().lower() == "greeting"
    else "respond_without_file_generation"
  )
  return [
    agent_step(
      index=start_index,
      agent=conversation_agent,
      action=conversation_action,
      input_payload={"intent": intent, "routing_result": routing_result},
      output_payload={
        "message": conversation_response.get("message"),
        "next_prompt_guidance": conversation_response.get("next_prompt_guidance") or [],
        "generated_files": 0,
      },
    ),
    agent_step(
      index=start_index + 1,
      agent="Memory Agent",
      action="prepare_conversation_memory",
      input_payload={"intent": intent},
      output_payload={
        "memory_kind": "conversation_summary",
        "content": text_value(conversation_response.get("message"), "Conversation turn handled."),
      },
    ),
  ]
