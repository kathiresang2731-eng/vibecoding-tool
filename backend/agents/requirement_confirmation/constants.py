from __future__ import annotations


CONFIRMATION_NAMESPACE = "confirmation"
CONFIRMATION_KEY = "pending_execution_brief"

REQUIREMENT_CONFIRMATION_CONTRACT = """
Return exactly this JSON shape. Do not add extra keys:
{
  "confirmation_required": true,
  "risk_level": "low|medium|high",
  "summary": "short concrete description of the intended result",
  "planned_changes": ["specific implementation step"],
  "assumptions": ["assumption the user should verify"],
  "open_questions": ["only questions that materially affect the result"],
  "scope_boundaries": ["what must remain unchanged"],
  "reason": "why confirmation is or is not required"
}
"""

CONFIRMATION_DECISION_CONTRACT = """
Return exactly this JSON shape. Do not add extra keys:
{
  "decision": "confirm|revise|cancel|new_request|unclear",
  "revision": "empty unless the user requested changes to the brief",
  "reason": "short explanation"
}
"""
