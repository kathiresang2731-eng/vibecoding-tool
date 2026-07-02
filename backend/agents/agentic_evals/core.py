from __future__ import annotations

from typing import Any

from .artifact import add_artifact_checks
from .constants import ARTIFACT_INTENTS, CONVERSATION_INTENTS, VALID_INTENTS
from .conversation import add_conversation_checks
from .scoring import add_check, summarize_checks
from .values import object_value, text_value


def evaluate_agentic_response(response: dict[str, Any]) -> dict[str, Any]:
  """Score a normalized generation response against the Worktual agentic contract."""

  checks: list[dict[str, Any]] = []
  multi_agent_system = object_value(response.get("multi_agent_system"))
  intent = text_value(multi_agent_system.get("intent"))
  runtime = object_value(multi_agent_system.get("agentic_runtime"))
  tool_setup = object_value(response.get("gemini_tool_calling_setup"))

  add_check(
    checks,
    name="route_intent",
    passed=intent in VALID_INTENTS,
    detail=f"intent={intent or 'missing'}",
    missing=[] if intent in VALID_INTENTS else ["multi_agent_system.intent"],
  )

  if intent in ARTIFACT_INTENTS:
    add_artifact_checks(checks, response=response, runtime=runtime, tool_setup=tool_setup, intent=intent)
  elif intent in CONVERSATION_INTENTS:
    add_conversation_checks(checks, runtime=runtime, tool_setup=tool_setup)
  else:
    add_check(
      checks,
      name="branch_contract",
      passed=False,
      detail="Cannot evaluate branch-specific checks without a valid route intent.",
      missing=["multi_agent_system.intent"],
    )

  return summarize_checks(checks)
