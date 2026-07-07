from __future__ import annotations

from typing import Any

from .values import string_list


def confirmation_conversation_response(brief: dict[str, Any], *, message: str | None = None) -> dict[str, Any]:
  return {
    "type": "needs_confirmation",
    "message": message or format_confirmation_message(brief),
    "next_prompt_guidance": [
      "Confirm and proceed",
      "Describe changes to this plan",
      "Cancel this request",
    ],
    "confirmation": public_confirmation_brief(brief),
  }


def format_confirmation_message(brief: dict[str, Any]) -> str:
  lines = [
    "Please confirm this execution brief before I start.",
    "",
    f"Goal: {brief.get('summary', 'Execute the requested work.')}",
    "",
    "Plan:",
  ]
  lines.extend(f"{index}. {item}" for index, item in enumerate(string_list(brief.get("planned_changes"), limit=6), start=1))
  assumptions = string_list(brief.get("assumptions"), limit=5)
  questions = string_list(brief.get("open_questions"), limit=5)
  boundaries = string_list(brief.get("scope_boundaries"), limit=5)
  if assumptions:
    lines.extend(["", "Assumptions:", *[f"- {item}" for item in assumptions]])
  if questions:
    lines.extend(["", "Open questions:", *[f"- {item}" for item in questions]])
  if boundaries:
    lines.extend(["", "Will preserve:", *[f"- {item}" for item in boundaries]])
  lines.extend(["", 'Reply "confirm" to proceed, describe changes to revise the brief, or cancel.'])
  return "\n".join(lines)


def public_confirmation_brief(brief: dict[str, Any]) -> dict[str, Any]:
  return {
    "status": brief.get("status", "pending"),
    "operation": brief.get("operation"),
    "risk_level": brief.get("risk_level"),
    "summary": brief.get("summary"),
    "planned_changes": string_list(brief.get("planned_changes"), limit=6),
    "assumptions": string_list(brief.get("assumptions"), limit=5),
    "open_questions": string_list(brief.get("open_questions"), limit=5),
    "scope_boundaries": string_list(brief.get("scope_boundaries"), limit=5),
  }
