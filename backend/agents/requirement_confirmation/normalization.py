from __future__ import annotations

from typing import Any

from .values import default_plan, normalize_enum, string_list, text


def normalize_confirmation_brief(raw: Any, *, user_prompt: str, operation: str) -> dict[str, Any]:
  if not isinstance(raw, dict):
    return deterministic_confirmation_brief(user_prompt, operation=operation, reason="Confirmation response was not an object.")

  required = raw.get("confirmation_required")
  if not isinstance(required, bool):
    required = operation == "website_generation"
  risk_level = normalize_enum(raw.get("risk_level"), {"low", "medium", "high"}, "medium")
  planned_changes = string_list(raw.get("planned_changes"), limit=6)
  if not planned_changes:
    planned_changes = default_plan(operation)
  return {
    "confirmation_required": True if operation == "website_generation" else required,
    "operation": operation,
    "original_request": user_prompt.strip(),
    "effective_request": user_prompt.strip(),
    "risk_level": risk_level,
    "summary": text(raw.get("summary"), f"Execute the requested {operation.replace('_', ' ')}."),
    "planned_changes": planned_changes,
    "assumptions": string_list(raw.get("assumptions"), limit=5),
    "open_questions": string_list(raw.get("open_questions"), limit=5),
    "scope_boundaries": string_list(raw.get("scope_boundaries"), limit=5)
    or (["Preserve unrelated existing files, content, layout, and behavior."] if operation == "website_update" else []),
    "reason": text(raw.get("reason"), "Prepared an execution brief before starting work."),
  }


def normalize_confirmation_decision(raw: Any) -> dict[str, str]:
  if not isinstance(raw, dict):
    return {"decision": "unclear", "revision": "", "reason": "Confirmation response was not an object."}
  return {
    "decision": normalize_enum(raw.get("decision"), {"confirm", "revise", "cancel", "new_request", "unclear"}, "unclear"),
    "revision": text(raw.get("revision"), ""),
    "reason": text(raw.get("reason"), "Classified the response against the pending execution brief."),
  }


def deterministic_confirmation_decision(user_message: str) -> dict[str, str] | None:
  lowered = user_message.strip().lower()
  if not lowered:
    return None
  confirm_markers = (
    "confirm and proceed",
    "confirm and continue",
    "confirm this execution brief",
    "proceed with this execution brief",
    "yes, proceed",
    "yes proceed",
    "go ahead and proceed",
    "approved",
    "looks good, proceed",
  )
  if lowered in {"confirm", "proceed", "yes", "yes.", "ok", "okay"} or any(marker in lowered for marker in confirm_markers):
    return {
      "decision": "confirm",
      "revision": "",
      "reason": "Matched explicit confirmation language without calling the routing model.",
    }
  cancel_markers = (
    "cancel the pending",
    "cancel execution brief",
    "cancel it",
    "cancel this",
    "cancel request",
    "cancel this request",
    "do not proceed",
    "stop this plan",
    "stop it",
    "cancel this brief",
  )
  if lowered in {"cancel", "cancel.", "stop", "stop."} or any(marker in lowered for marker in cancel_markers):
    return {
      "decision": "cancel",
      "revision": "",
      "reason": "Matched explicit cancellation language without calling the routing model.",
    }
  return None


def looks_like_confirmation_reply(user_message: str) -> bool:
  return deterministic_confirmation_decision(user_message) is not None


def deterministic_confirmation_brief(user_prompt: str, *, operation: str, reason: str) -> dict[str, Any]:
  return {
    "confirmation_required": True,
    "operation": operation,
    "original_request": user_prompt.strip(),
    "effective_request": user_prompt.strip(),
    "risk_level": "high" if operation == "website_generation" else "medium",
    "summary": f"Execute the requested {operation.replace('_', ' ')} while preserving unrelated project behavior.",
    "planned_changes": default_plan(operation),
    "assumptions": [],
    "open_questions": [],
    "scope_boundaries": ["Preserve unrelated existing files, content, layout, and behavior."] if operation == "website_update" else [],
    "reason": reason,
  }
