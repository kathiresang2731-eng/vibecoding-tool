from __future__ import annotations

import json
import re
from typing import Any

from backend.debug_trace import trace_print
from backend.agents.project_inspection import build_grounded_project_info_response
from backend.agents.prompts import CONVERSATION_SYSTEM_INSTRUCTION, build_conversation_response_prompt
from backend.agents.schema import ResponseContractError, sanitize_generation_response
from ..constants import DEFAULT_AGENT_TEAM, DEFAULT_TOOL_REGISTRY
from ..provider_utils import provider_name
from ..state import GenerationPipelineState
from ..tool_registry import log_tool_call
from .response_support import compact_user_prompt, fallback_greeting_message, deterministic_conversation_response
from .tools import build_selected_tool_arguments


def generate_conversation_response(state: GenerationPipelineState, client: Any) -> dict[str, Any]:
  trace_print(
    "ENTER",
    file=__file__,
    class_name="-",
    function="generate_conversation_response",
    intent=state.intent,
    next_tool=state.routing_result.get("next_tool"),
  )
  if state.conversation_response_override is not None:
    selected_tool = state.routing_result["next_tool"]
    log_tool_call(selected_tool, "output", state.conversation_response_override)
    trace_print(
      "EXIT",
      file=__file__,
      class_name="-",
      function="generate_conversation_response",
      intent=state.intent,
      next_tool=selected_tool,
      source="override",
    )
    return state.conversation_response_override
  selected_tool = state.routing_result["next_tool"]
  trace_print(
    "ENTER",
    file=__file__,
    class_name="ConversationTool",
    function=selected_tool,
    intent=state.intent,
  )
  log_tool_call(
    selected_tool,
    "input",
    build_selected_tool_arguments(state, selected_tool),
  )
  grounded_response = build_grounded_project_info_response(
    state.user_prompt,
    state.routing_result.get("project_context"),
  )
  if grounded_response is not None:
    project_context = state.routing_result.get("project_context") if isinstance(state.routing_result.get("project_context"), dict) else {}
    normalized = {
      "type": state.intent,
      "message": str(grounded_response["message"]).strip(),
      "received_message": state.user_prompt,
      "routing_result": state.routing_result,
      "next_prompt_guidance": [
        str(item).strip()
        for item in grounded_response.get("next_prompt_guidance", [])
        if str(item).strip()
      ],
      "target_resolution": state.routing_result.get("target_resolution") or project_context.get("target_resolution") or {},
      "grounding": grounded_response.get("grounding", {}),
    }
    log_tool_call(selected_tool, "grounded_output", normalized)
    trace_print(
      "EXIT",
      file=__file__,
      class_name="ConversationTool",
      function=selected_tool,
      source="grounded_project_context",
    )
    trace_print(
      "EXIT",
      file=__file__,
      class_name="-",
      function="generate_conversation_response",
      intent=state.intent,
      next_tool=selected_tool,
    )
    return normalized
  prompt = build_conversation_response_prompt(
    state.user_prompt,
    intent=state.intent,
    selected_tool=selected_tool,
    routing_result=state.routing_result,
  )
  try:
    if state.intent == "web_search" and hasattr(client, "generate_json_with_search"):
      response = client.generate_json_with_search(
        prompt,
        system_instruction=CONVERSATION_SYSTEM_INSTRUCTION,
        trace_label=selected_tool,
      )
    else:
      response = client.generate_json(
        prompt,
        system_instruction=CONVERSATION_SYSTEM_INSTRUCTION,
        trace_label=selected_tool,
      )
  except Exception as exc:
    fallback = deterministic_conversation_response(state, error=str(exc))
    log_tool_call(selected_tool, "fallback_output", fallback)
    trace_print(
      "EXIT",
      file=__file__,
      class_name="ConversationTool",
      function=selected_tool,
      source="fallback",
    )
    trace_print(
      "EXIT",
      file=__file__,
      class_name="-",
      function="generate_conversation_response",
      intent=state.intent,
      next_tool=selected_tool,
      source="fallback",
    )
    return fallback
  log_tool_call(selected_tool, "raw_output", response)
  normalized = normalize_conversation_response(response, state)
  log_tool_call(selected_tool, "output", normalized)
  trace_print(
    "EXIT",
    file=__file__,
    class_name="ConversationTool",
    function=selected_tool,
    source="model",
  )
  trace_print(
    "EXIT",
    file=__file__,
    class_name="-",
    function="generate_conversation_response",
    intent=state.intent,
    next_tool=selected_tool,
    source="model",
  )
  return normalized


def normalize_conversation_response(response: dict[str, Any], state: GenerationPipelineState) -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Conversation tool response must be a JSON object.")

  message = response.get("message")
  guidance = response.get("next_prompt_guidance")
  if not isinstance(message, str) or not message.strip():
    raise ResponseContractError("Conversation tool response missing message.")
  if not isinstance(guidance, list) or not guidance or not all(isinstance(item, str) and item.strip() for item in guidance):
    raise ResponseContractError("Conversation tool response missing next_prompt_guidance.")

  return {
    "type": state.intent,
    "message": clean_conversation_message(message, intent=state.intent, user_prompt=state.user_prompt),
    "received_message": state.user_prompt,
    "routing_result": state.routing_result,
    "next_prompt_guidance": [
      clean_conversation_message(item, intent=state.intent, user_prompt=state.user_prompt)
      for item in guidance
    ],
  }


def _prompt_explicitly_asks_for_code(user_prompt: str) -> bool:
  return bool(re.search(r"\b(show|give|print|include|paste|provide)\b.{0,40}\b(code|source|jsx|tsx|snippet|file)\b", str(user_prompt or "").lower()))


def _remove_code_like_project_info(value: str) -> str:
  text = re.sub(r"```[\s\S]*?```", "", value)
  cleaned_lines: list[str] = []
  for line in text.splitlines():
    stripped = line.strip()
    if re.search(r"\b(className|onClick|useState|useEffect|export\s+default|import\s+.+\s+from)\b", stripped):
      continue
    if re.search(r"</?[A-Za-z][^>]{0,120}>", stripped):
      continue
    cleaned_lines.append(line)
  return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def clean_conversation_message(value: str, *, intent: str, user_prompt: str = "") -> str:
  text = str(value or "").strip()
  if intent == "project_info":
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "- ", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    if not _prompt_explicitly_asks_for_code(user_prompt):
      text = _remove_code_like_project_info(text)
  return text.strip()
