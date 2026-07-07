from __future__ import annotations

from typing import Any

from .normalization import (
  deterministic_confirmation_brief,
  deterministic_confirmation_decision,
  normalize_confirmation_brief,
  normalize_confirmation_decision,
)
from .prompts import build_confirmation_decision_prompt, build_requirement_confirmation_prompt

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event


def prepare_confirmation_brief(client: Any, user_prompt: str, *, operation: str) -> dict[str, Any]:
  try:
    raw = client.generate_json(
      build_requirement_confirmation_prompt(user_prompt, operation=operation),
      trace_label="prepare_requirement_confirmation",
    )
    brief = normalize_confirmation_brief(raw, user_prompt=user_prompt, operation=operation)
  except Exception as exc:
    brief = deterministic_confirmation_brief(user_prompt, operation=operation, reason=f"Confirmation model unavailable: {str(exc)[:240]}")
  log_query_event(
    "requirements.confirmation.prepared",
    status="completed",
    payload={
      "operation": operation,
      "confirmation_required": brief["confirmation_required"],
      "risk_level": brief["risk_level"],
      "summary": brief["summary"],
    },
    provider="gemini",
  )
  return brief


def evaluate_confirmation_reply(client: Any, user_message: str, pending_brief: dict[str, Any]) -> dict[str, str]:
  decision = deterministic_confirmation_decision(user_message)
  if decision is None:
    try:
      raw = client.generate_json(
        build_confirmation_decision_prompt(user_message, pending_brief),
        trace_label="evaluate_requirement_confirmation",
      )
      decision = normalize_confirmation_decision(raw)
    except Exception as exc:
      decision = deterministic_confirmation_decision(user_message) or {
        "decision": "unclear",
        "revision": "",
        "reason": f"Confirmation decision model unavailable: {str(exc)[:240]}",
      }
  log_query_event(
    "requirements.confirmation.decision",
    status="completed",
    payload={"decision": decision["decision"], "reason": decision["reason"]},
    provider="gemini",
  )
  return decision
