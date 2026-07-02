from __future__ import annotations

import json
from typing import Any

from .constants import (
  SPECIALIST_PROMPT_BRIEF_MAX_CHARS,
  SPECIALIST_PROMPT_PLAN_MAX_CHARS,
)
from .utils import sha256_text

try:
  from ..prompting.policies import PROMPT_POLICY_VERSION, prompt_policy_block
except ImportError:
  from agents.prompting.policies import PROMPT_POLICY_VERSION, prompt_policy_block


def generic_dynamic_agent_prompt(name: str, capability: str, domain: str) -> str:
  return (
    f"You are the {name}. Provide reusable, domain-agnostic structured recommendations "
    f"for the {capability} capability in {domain} website projects. Do not hard-code "
    "a brand, project name, user prompt, color palette, file path, or one-off business context. "
    "Do not request deletes or direct file writes. Keep guidance compatible with the shared "
    f"agentic prompt policy: {PROMPT_POLICY_VERSION}. "
    "Return compact JSON only."
  )


def build_specialist_task_prompt(
  *,
  task_item: dict[str, Any],
  user_prompt: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
) -> str:
  return (
    "Return strict compact JSON with keys status, summary, recommendations, requirements, risks, candidate_changes.\n"
    "Keep summary under 700 characters. Return at most 5 recommendations, 5 requirements, and 3 risks. "
    "Do not generate full React files, full App.jsx content, or large source-code blocks; the Code Generator owns final implementation.\n"
    f"Shared prompt policy:\n{prompt_policy_block(include_generation=True, include_update=True)}\n"
    f"Task: {compact_json_for_prompt(task_item, max_chars=2500)}\n"
    f"User prompt: {user_prompt}\n"
    f"Brief: {compact_json_for_prompt(brief, max_chars=SPECIALIST_PROMPT_BRIEF_MAX_CHARS)}\n"
    f"Current website plan: {compact_json_for_prompt(plan, max_chars=SPECIALIST_PROMPT_PLAN_MAX_CHARS)}\n"
    "Candidate changes are optional proposals only. Prefer candidate_changes: [] unless this exact task cannot be represented as "
    "plain planning guidance. Never request deletes or claim that files were written."
  )


def compact_json_for_prompt(value: Any, *, max_chars: int) -> str:
  try:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  except TypeError:
    text = json.dumps(str(value), ensure_ascii=False)
  if len(text) <= max_chars:
    return text
  return json.dumps(
    {
      "_truncated": True,
      "original_chars": len(text),
      "sha256": sha256_text(text),
      "preview": text[:max_chars],
    },
    ensure_ascii=False,
    separators=(",", ":"),
  )
