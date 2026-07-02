from __future__ import annotations

import re
from typing import Any

from ..budget_config import AGENT_BUDGETS
from ..prompts import ROUTING_SYSTEM_INSTRUCTION, build_routing_prompt, build_routing_repair_prompt
from ..prompt_context import ORCHESTRATOR_CONTEXT_MARKER, current_user_prompt
from ..schema import ResponseContractError
from .constants import ROUTING_INTENT_CONFIG
from ..followup_routing import apply_existing_project_routing_bias, is_explicit_new_project_request
from .tool_registry import log_tool_call

try:
  from ..gemini_client.parsing import salvage_json_string_fields
except ImportError:
  from agents.gemini_client.parsing import salvage_json_string_fields

ROUTING_CONTEXT_MARKER = ORCHESTRATOR_CONTEXT_MARKER
ROUTING_RESPONSE_SCHEMA: dict[str, Any] = {
  "type": "object",
  "properties": {
    "intent": {
      "type": "string",
      "enum": [
        "greeting",
        "needs_more_detail",
        "project_info",
        "simple_code",
        "website_generation",
        "website_update",
      ],
    },
    "next_action": {"type": "string"},
    "next_tool": {"type": "string"},
    "reason": {"type": "string", "maxLength": 220},
  },
  "required": ["intent", "next_action", "next_tool", "reason"],
}

WEBSITE_SPEC_MARKERS = (
  "website",
  "web app",
  "webapp",
  "dashboard",
  "onboarding",
  "backend",
  "frontend",
  "api",
  "color",
  "colour",
  "channel",
  "python",
  "react",
  "auth",
  "ccaas",
  "whatsapp",
  "instagram",
  "webchat",
  "settings",
  "report",
  "operations",
  "full stack",
  "full-stack",
)

SIMPLE_CODE_WEB_CONTEXT_MARKERS = (
  "website",
  "web site",
  "web app",
  "webapp",
  "landing page",
  "frontend",
  "react app",
  "vite",
  "dashboard",
  "page",
  "this site",
  "this website",
)

SIMPLE_CODE_REQUEST_MARKERS = (
  "write a code",
  "write code",
  "generate code",
  "create code",
  "give me code",
  "provide code",
  "provide a code",
  "write a program",
  "generate a program",
  "create a program",
  "provide a program",
  "java program",
  "python program",
  "standalone code",
  "standalone program",
)

SIMPLE_CODE_TASK_MARKERS = (
  "algorithm",
  "script",
  "function",
  "program",
  "number",
  "prime",
  "neon",
  "armstrong",
  "palindrome",
  "fibonacci",
  "factorial",
  "reverse",
  "sort",
  "array",
  "string",
  "matrix",
  "calculator",
  "pattern",
)

SIMPLE_CODE_LANGUAGE_MARKERS = (
  "python",
  "java",
  "javascript",
  "typescript",
  "rust",
  "golang",
  " go ",
  "c++",
  "c#",
  "php",
  "ruby",
  "kotlin",
  "swift",
)


def routing_user_message(prompt: str) -> str:
  return current_user_prompt(prompt)


def deterministic_routing_result(prompt: str) -> dict[str, str] | None:
  lowered = prompt.strip().lower()
  if not lowered:
    return None
  greeting_markers = ("hi", "hello", "hey", "good morning", "good evening")
  if lowered in greeting_markers or (len(lowered) <= 24 and any(lowered.startswith(marker) for marker in greeting_markers)):
    expected = ROUTING_INTENT_CONFIG["greeting"]
    return {
      "intent": "greeting",
      "next_action": expected["next_action"],
      "next_tool": expected["next_tool"],
      "reason": "Matched greeting language without calling the routing model.",
    }
  if looks_like_simple_code_request(lowered):
    expected = ROUTING_INTENT_CONFIG["simple_code"]
    return {
      "intent": "simple_code",
      "next_action": expected["next_action"],
      "next_tool": expected["next_tool"],
      "reason": "Matched standalone code request without calling the routing model.",
    }
  if _looks_like_project_file_update(lowered):
    expected = ROUTING_INTENT_CONFIG["website_update"]
    return {
      "intent": "website_update",
      "next_action": expected["next_action"],
      "next_tool": expected["next_tool"],
      "reason": "Matched named project-file update without calling the routing model.",
    }
  return None


def looks_like_simple_code_request(lowered_prompt: str) -> bool:
  if any(marker in lowered_prompt for marker in SIMPLE_CODE_WEB_CONTEXT_MARKERS):
    return False
  if any(marker in lowered_prompt for marker in SIMPLE_CODE_REQUEST_MARKERS):
    return True
  wants_code_action = any(marker in lowered_prompt for marker in ("write ", "create ", "generate ", "make ", "give me ", "provide "))
  has_code_target = any(marker in lowered_prompt for marker in SIMPLE_CODE_TASK_MARKERS)
  has_language = any(marker in f" {lowered_prompt} " for marker in SIMPLE_CODE_LANGUAGE_MARKERS)
  return wants_code_action and has_code_target and (has_language or "code" in lowered_prompt or "program" in lowered_prompt)


def looks_like_website_generation_request(lowered_prompt: str) -> bool:
  if not lowered_prompt:
    return False
  update_markers = (
    "update ",
    "change ",
    "fix ",
    "edit ",
    "modify ",
    "replace ",
    "remove ",
    "resolve ",
    "patch ",
  )
  if any(marker in lowered_prompt for marker in update_markers):
    return False
  wants_build = any(
    marker in lowered_prompt
    for marker in ("build ", "create ", "generate", "regenerate", "rebuild", "make ")
  )
  if not wants_build:
    return False
  website_hits = sum(1 for marker in WEBSITE_SPEC_MARKERS if marker in lowered_prompt)
  structured_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", lowered_prompt))
  wants_site = any(
    marker in lowered_prompt
    for marker in (
      "website",
      "web site",
      "web app",
      "webapp",
      "frontend",
      "react app",
      "crm",
      "dashboard",
      "landing page",
      "requirement",
      "requirements",
    )
  )
  return wants_site and (
    website_hits >= 2
    or len(lowered_prompt) > 80
    or structured_items >= 3
    or "based on requirement" in lowered_prompt
  )


def _looks_like_project_file_update(lowered_prompt: str) -> bool:
  if any(secret in lowered_prompt for secret in (".env", "env.example", "environment file")):
    return True
  if re.search(r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*\.(?:js|jsx|ts|tsx|css|html|json|py|java|go|php|rb|sql|env)\b", lowered_prompt):
    return True
  return False


def heuristic_routing_result(prompt: str) -> dict[str, str] | None:
  """Fallback when routing JSON is malformed — structural signals only, no domain presets."""
  lowered = prompt.strip().lower()
  if not lowered:
    return None
  if any(marker in lowered for marker in ("fix ", "update ", "change ", "edit ", "modify ", "remove ", "bug", "error")):
    return None
  structured_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", lowered, flags=re.MULTILINE))
  wants_build = any(marker in lowered for marker in ("i want", "build ", "create ", "generate", "make ", "regenerate", "rebuild"))
  if wants_build and (structured_items >= 3 or len(lowered) > 100):
    expected = ROUTING_INTENT_CONFIG["website_generation"]
    return {
      "intent": "website_generation",
      "next_action": expected["next_action"],
      "next_tool": expected["next_tool"],
      "reason": "Matched structured website build language after routing JSON failure.",
    }
  return None


def salvage_routing_from_error(exc: Exception) -> dict[str, Any] | None:
  error_text = str(exc)
  if "{" not in error_text:
    return None
  return salvage_json_string_fields(
    error_text[error_text.find("{") :],
    fields=("intent", "next_action", "next_tool", "reason"),
    required=("intent",),
  )


def routing_fallback_after_model_error(prompt: str, exc: Exception) -> dict[str, str] | None:
  salvaged = salvage_routing_from_error(exc)
  if isinstance(salvaged, dict):
    try:
      return normalize_routing_result(salvaged, prompt=prompt)
    except ResponseContractError:
      pass
  return deterministic_routing_result(prompt) or heuristic_routing_result(prompt)


def route_generation_action_tool(prompt: str, client: Any) -> dict[str, Any]:
  user_message = routing_user_message(prompt)
  deterministic = deterministic_routing_result(user_message)
  if deterministic is not None:
    record_deterministic_provider_trace(client, "route_generation_action")
    log_tool_call(
      "route_generation_action",
      "input",
      {
        "message": user_message,
        "conversation_context": "website_builder_chat",
        "routing_policy": "deterministic_fast_path",
      },
    )
    log_tool_call("route_generation_action", "output", deterministic)
    return deterministic
  log_tool_call(
    "route_generation_action",
    "input",
    {
      "message": user_message,
      "conversation_context": "website_builder_chat",
      "routing_policy": "llm_only",
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

def normalize_routing_result(response: dict[str, Any], *, prompt: str = "") -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Routing tool response must be a JSON object.")

  intent = normalize_enum_value(response.get("intent"))
  if intent not in ROUTING_INTENT_CONFIG:
    raise ResponseContractError("Routing tool response has invalid intent.")

  expected = ROUTING_INTENT_CONFIG[intent]
  reason = response.get("reason")
  if not isinstance(reason, str) or not reason.strip():
    raise ResponseContractError("Routing tool response missing reason.")
  reason_text = reason.strip()
  if len(reason_text) > 220:
    reason_text = reason_text[:200].rstrip() + "..."

  return {
    "intent": intent,
    "next_action": expected["next_action"],
    "next_tool": expected["next_tool"],
    "reason": reason_text,
  }

def normalize_enum_value(value: Any) -> str:
  if not isinstance(value, str):
    return ""
  return value.strip().lower().replace("-", "_").replace(" ", "_")
