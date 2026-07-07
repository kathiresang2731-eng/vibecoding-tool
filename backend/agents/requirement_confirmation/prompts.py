from __future__ import annotations

import json
from typing import Any

from .constants import CONFIRMATION_DECISION_CONTRACT, REQUIREMENT_CONFIRMATION_CONTRACT
from .presentation import public_confirmation_brief
try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block


def build_requirement_confirmation_prompt(user_prompt: str, *, operation: str) -> str:
  return f"""
User request:
{user_prompt.strip()}

Operation:
{operation}

You are the Requirement Confirmation Agent. Prepare a concise execution brief
before expensive or high-impact website-builder work starts.

Shared prompt policy:
{prompt_policy_block(include_generation=operation != "update", include_update=operation == "update")}

Rules:
- New website generation must require confirmation.
- Broad redesigns, full regeneration, ambiguous updates, destructive changes,
  and changes that may replace existing content must require confirmation.
- Deleting files, pruning missing files, replacing local uploaded folders,
  editing secrets/config credentials, or rewriting large unrelated files always
  requires explicit approval.
- A clear low-risk scoped update may skip confirmation. Examples include
  changing one color, replacing one known text value, changing a page-size
  constant, or fixing a clearly identified small bug.
- Describe the intended result and implementation steps, not internal model
  reasoning or agent names.
- Keep planned_changes to at most 6 concrete steps.
- Keep assumptions, questions, and scope boundaries to at most 5 items each.
- Scope boundaries must explicitly protect unrelated existing code and UI for
  website updates.

{REQUIREMENT_CONFIRMATION_CONTRACT}
"""


def format_confirmation_brief_for_generation(brief: dict[str, Any] | None) -> str:
  if not isinstance(brief, dict) or not brief:
    return ""

  def _lines(key: str) -> list[str]:
    raw = brief.get(key)
    if not isinstance(raw, list):
      return []
    return [str(item).strip() for item in raw if str(item or "").strip()]

  summary = str(brief.get("summary") or "").strip()
  planned = _lines("planned_changes")
  assumptions = _lines("assumptions")
  boundaries = _lines("scope_boundaries")
  if not any([summary, planned, assumptions, boundaries]):
    return ""

  lines = ["## Confirmed execution brief"]
  if summary:
    lines.append(f"Goal: {summary}")
  if planned:
    lines.append("Planned changes:")
    lines.extend(f"- {item}" for item in planned[:6])
  if assumptions:
    lines.append("Assumptions:")
    lines.extend(f"- {item}" for item in assumptions[:5])
  if boundaries:
    lines.append("Scope boundaries:")
    lines.extend(f"- {item}" for item in boundaries[:5])
  return "\n".join(lines).strip()


def build_confirmation_decision_prompt(user_message: str, pending_brief: dict[str, Any]) -> str:
  return f"""
Pending execution brief:
{json.dumps(public_confirmation_brief(pending_brief), ensure_ascii=False, indent=2)}

Latest user message:
{user_message.strip()}

You are the Requirement Confirmation Agent. Decide how the latest message
relates to the pending execution brief.

Shared prompt policy:
{prompt_policy_block(include_generation=True, include_update=True)}

Rules:
- confirm: the user clearly approves or asks to proceed with the pending brief.
- revise: the user wants to change or add requirements to the pending brief.
- cancel: the user explicitly cancels or rejects the pending work.
- new_request: the user starts a separate task unrelated to the pending brief.
- unclear: approval is ambiguous and execution must not start.
- Never treat a question about the brief as confirmation.

{CONFIRMATION_DECISION_CONTRACT}
"""
