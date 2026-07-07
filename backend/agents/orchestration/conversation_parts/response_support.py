from __future__ import annotations

from typing import Any

from backend.agents.orchestration.state import GenerationPipelineState


def compact_user_prompt(value: str, *, max_length: int = 80) -> str:
  compacted = " ".join(str(value or "").strip().split())
  if not compacted:
    return "hello"
  return compacted[:max_length].rstrip()


def fallback_greeting_message(state: GenerationPipelineState) -> str:
  greeting = compact_user_prompt(state.user_prompt)
  return (
    f"Hey{'' if greeting.lower() in {'hi', 'hello', 'hey'} else f' — {greeting.capitalize()}'}! "
    "I'm ready to help you build. What website or app do you have in mind, and who is it for?"
  )


def deterministic_conversation_response(state: GenerationPipelineState, *, error: str) -> dict[str, Any]:
  if state.intent == "greeting":
    message = fallback_greeting_message(state)
    guidance = ["Website type and brand name", "Target audience", "Sections and features", "Visual style"]
  elif "current-project modification" in str(state.routing_result.get("reason") or "").lower():
    message = (
      "Sure—what exactly would you like to modify? Please mention the page or "
      "component and the expected change, such as updating text, changing colors, "
      "adding a feature, or fixing an interaction."
    )
    guidance = ["Page or component", "Current behavior", "Expected change", "Visual or functional requirements"]
  elif state.routing_result.get("next_tool") != "request_website_details":
    message = (
      "I could not prepare a reliable answer for this turn. No generation, update, "
      "or project file write was started."
    )
    guidance = ["Retry the request", "Add context if the question depends on the current project"]
  else:
    prompt_context = compact_user_prompt(state.user_prompt)
    message = (
      f"I need a little more detail for: {prompt_context}.\n"
      "Please include the business type, brand name, audience, required sections, visual style, and must-have features."
    )
    guidance = ["Business or website type", "Brand name and audience", "Required sections", "Style and features"]
  return {
    "type": state.intent,
    "message": message,
    "received_message": state.user_prompt,
    "routing_result": {
      **state.routing_result,
      "fallback_reason": f"Gemini conversation response was unavailable: {error[:240]}",
    },
    "next_prompt_guidance": guidance,
  }
