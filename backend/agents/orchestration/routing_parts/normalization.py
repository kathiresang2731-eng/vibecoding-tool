from __future__ import annotations

from typing import Any

from backend.agents.schema import ResponseContractError
from backend.agents.orchestration.constants import ROUTING_INTENT_CONFIG


def normalize_routing_result(response: dict[str, Any], *, prompt: str = "") -> dict[str, Any]:
  if not isinstance(response, dict):
    raise ResponseContractError("Routing tool response must be a JSON object.")

  intent = normalize_enum_value(response.get("intent"))
  if intent not in ROUTING_INTENT_CONFIG:
    raise ResponseContractError("Routing tool response has invalid intent.")
  missing_fields = [
    str(item).strip()
    for item in (response.get("missing_fields") or [])
    if str(item).strip()
  ] if isinstance(response.get("missing_fields"), list) else []
  clarification_question = (
    str(response.get("clarification_question") or "").strip()
    if intent == "needs_more_detail"
    else ""
  )
  understanding = {
    "actionable": intent != "needs_more_detail",
    "clarification_required": intent == "needs_more_detail",
    "operation": intent,
    "missing_fields": missing_fields,
    "clarification_question": clarification_question,
    "decision_source": "llm_semantic_router",
  }

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
    "request_understanding": understanding,
  }


def normalize_enum_value(value: Any) -> str:
  if not isinstance(value, str):
    return ""
  return value.strip().lower().replace("-", "_").replace(" ", "_")
