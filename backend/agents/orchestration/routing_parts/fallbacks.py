from __future__ import annotations

from typing import Any

from backend.agents.prompt_context import current_user_prompt
from backend.agents.schema import ResponseContractError
from .normalization import normalize_routing_result
from .markers import (
  looks_like_document_artifact_request,
  looks_like_simple_code_request,
  looks_like_time_sensitive_research_request,
  looks_like_research_or_planning_request,
  looks_like_website_generation_request,
)

try:
  from ..gemini_client.parsing import salvage_json_string_fields
except ImportError:
  from agents.gemini_client.parsing import salvage_json_string_fields


def routing_user_message(prompt: str) -> str:
  return current_user_prompt(prompt)


def deterministic_routing_result(prompt: str) -> dict[str, str] | None:
  """Compatibility facade: intent routing is intentionally LLM-only."""
  return None


def heuristic_routing_result(prompt: str) -> dict[str, str] | None:
  """Compatibility facade: model failures never guess an intent from text."""
  return None


def non_website_routing_fallback(prompt: str) -> dict[str, str] | None:
  lowered = str(prompt or "").strip().lower()
  if not lowered or looks_like_website_generation_request(lowered):
    return None
  if looks_like_simple_code_request(lowered):
    return normalize_routing_result(
      {
        "intent": "simple_code",
        "reason": "Safe fallback selected standalone code generation after router error.",
      },
      prompt=prompt,
    )
  if looks_like_document_artifact_request(lowered):
    return normalize_routing_result(
      {
        "intent": "document_artifact",
        "reason": "Safe fallback selected document artifact generation after router error.",
      },
      prompt=prompt,
    )
  if looks_like_time_sensitive_research_request(lowered):
    return normalize_routing_result(
      {
        "intent": "web_search",
        "reason": "Safe fallback selected web research after router error.",
      },
      prompt=prompt,
    )
  if looks_like_research_or_planning_request(lowered):
    return normalize_routing_result(
      {
        "intent": "general_query",
        "reason": "Safe fallback selected planning response after router error.",
      },
      prompt=prompt,
    )
  return None


def salvage_routing_from_error(exc: Exception) -> dict[str, Any] | None:
  error_text = str(exc)
  if "{" not in error_text:
    return None
  return salvage_json_string_fields(error_text[error_text.find("{") :], fields=("intent", "next_action", "next_tool", "reason"), required=("intent",))


def routing_fallback_after_model_error(prompt: str, exc: Exception) -> dict[str, str] | None:
  salvaged = salvage_routing_from_error(exc)
  if isinstance(salvaged, dict):
    try:
      return normalize_routing_result(salvaged, prompt=prompt)
    except ResponseContractError:
      pass
  return non_website_routing_fallback(prompt)
