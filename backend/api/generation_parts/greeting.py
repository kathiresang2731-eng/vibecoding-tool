from __future__ import annotations

from typing import Any

from backend.debug_trace import trace_print

try:
  from backend.agents.orchestration.conversation import (
    build_conversation_generation_response,
    deterministic_conversation_response,
    generate_conversation_response,
  )
  from backend.agents.orchestration.state import GenerationPipelineState
  from backend.agents.providers import DUAL_PROVIDER_ROLE
except ImportError:
  from backend.agents.orchestration.conversation import (
    build_conversation_generation_response,
    deterministic_conversation_response,
    generate_conversation_response,
  )
  from backend.agents.orchestration.state import GenerationPipelineState
  from backend.agents.providers import DUAL_PROVIDER_ROLE


_SIMPLE_GREETING_VALUES = {
  "hi",
  "hii",
  "hiii",
  "hello",
  "hey",
  "hey there",
  "hello there",
  "good morning",
  "good afternoon",
  "good evening",
}


def is_simple_greeting_prompt(prompt: str) -> bool:
  normalized = " ".join(str(prompt or "").strip().lower().replace("!", " ").replace(".", " ").split())
  return normalized in _SIMPLE_GREETING_VALUES


def build_greeting_fast_path_routing_result(*, llm_authored: bool) -> dict[str, Any]:
  return {
    "intent": "greeting",
    "next_action": "respond_and_collect_website_brief",
    "next_tool": "handle_greeting",
    "confidence": 1.0,
    "reason": (
      "Simple greeting was handled by the LLM greeting fast path."
      if llm_authored
      else "Simple greeting was handled by the deterministic greeting fallback."
    ),
  }


def greeting_fast_path_adk_usage(*, llm_authored: bool) -> dict[str, Any]:
  return {
    "enabled": False,
    "runtime": "llm-greeting-fast-path" if llm_authored else "deterministic-greeting-fallback",
    "adk_agents": [
      {
        "adk_type": "LlmAgent",
        "name": "intent_router_agent",
        "purpose": "Handles simple greeting turns by calling the greeting response tool before any generation flow starts.",
      },
      {
        "adk_type": "AgentTool",
        "name": "handle_greeting_tool",
        "purpose": "Intent Router owned fast path for greeting-only turns without artifact generation.",
      },
    ],
    "notes": [
      (
        "Simple greeting handled by the selected model without full routing or artifact generation."
        if llm_authored
        else "Simple greeting handled by fallback without full routing or artifact generation."
      )
    ],
  }


def normalize_greeting_lines(message: str) -> str:
  lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
  if not lines:
    return "Hi there — tell me what website or app you'd like to create."
  return "\n".join(lines[:3])


def build_fast_greeting_generation(prompt: str, model_provider: Any | None = None) -> dict[str, Any]:
  trace_print(
    "ENTER",
    file=__file__,
    class_name="-",
    function="build_fast_greeting_generation",
    llm_authored=model_provider is not None,
  )
  llm_authored = model_provider is not None
  routing_result = {
    **build_greeting_fast_path_routing_result(llm_authored=llm_authored),
  }
  state = GenerationPipelineState(
    user_prompt=prompt,
    intent="greeting",
    routing_result=routing_result,
    prepared_sections={
      "google_adk_usage": greeting_fast_path_adk_usage(llm_authored=llm_authored)
    },
  )
  if model_provider is not None:
    try:
      conversation = generate_conversation_response(state, model_provider)
      conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
    except Exception:
      conversation = deterministic_conversation_response(state, error="greeting orchestration fallback")
      conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
  else:
    conversation = deterministic_conversation_response(state, error="deterministic greeting fallback")
    conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
  response = build_conversation_generation_response(state, conversation)
  trace_print(
    "EXIT",
    file=__file__,
    class_name="-",
    function="build_fast_greeting_generation",
    llm_authored=llm_authored,
  )
  return response
