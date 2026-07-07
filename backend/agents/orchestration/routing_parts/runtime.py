from __future__ import annotations

from typing import Any

from backend.agents.budget_config import AGENT_BUDGETS
from backend.agents.prompts import ROUTING_SYSTEM_INSTRUCTION, build_routing_prompt, build_routing_repair_prompt
from backend.agents.orchestration.tool_registry import log_tool_call
from backend.agents.schema import ResponseContractError
from .heuristics import routing_fallback_after_model_error, routing_user_message
from .normalization import normalize_routing_result


def route_generation_action_tool(prompt: str, client: Any) -> dict[str, Any]:
  user_message = routing_user_message(prompt)
  log_tool_call(
    "route_generation_action",
    "input",
    {
      "message": user_message,
      "conversation_context": "website_builder_chat",
      "routing_policy": "llm_semantic_router",
    },
  )
  try:
    response = client.generate_json(
      build_routing_prompt(user_message),
      system_instruction=ROUTING_SYSTEM_INSTRUCTION,
      trace_label="route_generation_action",
      response_schema=ROUTING_RESPONSE_SCHEMA,
      max_output_tokens=AGENT_BUDGETS.routing_output_tokens,
    )
  except Exception as exc:
    log_tool_call(
      "route_generation_action",
      "model_error",
      {
        "message": user_message,
        "error": str(exc),
        "routing_policy": "model_required",
      },
    )
    fallback = routing_fallback_after_model_error(user_message, exc)
    if fallback is not None:
      log_tool_call("route_generation_action", "deterministic_fallback", fallback)
      return fallback
    raise ResponseContractError(
      f"Routing model failed during route_generation_action; no generation actions were started. {str(exc)[:240]}"
    ) from exc
  log_tool_call("route_generation_action", "raw_output", response)
  try:
    normalized = normalize_routing_result(response, prompt=user_message)
    log_tool_call("route_generation_action", "output", normalized)
    return normalized
  except ResponseContractError:
    log_tool_call(
      "route_generation_action",
      "repair_input",
      {
        "message": prompt,
        "invalid_response": response,
      },
    )
    try:
      repaired_response = client.generate_json(
        build_routing_repair_prompt(user_message, response),
        system_instruction=ROUTING_SYSTEM_INSTRUCTION,
        trace_label="route_generation_action_repair",
        response_schema=ROUTING_RESPONSE_SCHEMA,
        max_output_tokens=AGENT_BUDGETS.routing_output_tokens,
      )
    except Exception as exc:
      log_tool_call(
        "route_generation_action",
        "repair_model_error",
        {
          "message": prompt,
          "invalid_response": response,
          "error": str(exc),
          "routing_policy": "model_required",
        },
      )
      fallback = routing_fallback_after_model_error(user_message, exc)
      if fallback is not None:
        log_tool_call("route_generation_action", "deterministic_fallback", fallback)
        return fallback
      raise ResponseContractError(
        f"Routing repair failed during route_generation_action; no generation actions were started. {str(exc)[:240]}"
      ) from exc
    log_tool_call("route_generation_action", "repair_raw_output", repaired_response)
    normalized = normalize_routing_result(repaired_response, prompt=user_message)
    log_tool_call("route_generation_action", "output", normalized)
    return normalized


def record_deterministic_provider_trace(client: Any, trace_label: str) -> None:
  trace_labels = getattr(client, "trace_labels", None)
  if isinstance(trace_labels, list):
    trace_labels.append(trace_label)


ROUTING_RESPONSE_SCHEMA: dict[str, Any] = {
  "type": "object",
  "properties": {
    "intent": {
      "type": "string",
      "enum": [
        "greeting",
        "question",
        "general_query",
        "web_search",
        "needs_more_detail",
        "project_info",
        "simple_code",
        "document_artifact",
        "website_generation",
        "website_update",
      ],
    },
    "next_action": {"type": "string"},
    "next_tool": {"type": "string"},
    "reason": {"type": "string", "maxLength": 220},
    "missing_fields": {
      "type": "array",
      "items": {"type": "string"},
    },
    "clarification_question": {"type": "string"},
  },
  "required": ["intent", "next_action", "next_tool", "reason"],
}
