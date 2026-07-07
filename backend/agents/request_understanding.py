from __future__ import annotations

import re
from typing import Any

UNDERSPECIFIED_UPDATE_PATTERNS = (
  r"(?:i\s+)?(?:want|need|would\s+like)\s+to\s+(?:do|make)?\s*(?:some|a|few)?\s*"
  r"(?:modification|modifications|change|changes|update|updates)\s+"
  r"(?:in|to|on)\s+(?:that|this|the|my|our)\s+(?:website|site|project|app|application)",
  r"(?:please\s+)?(?:modify|update|change|edit)\s+(?:that|this|the|my|our)\s+"
  r"(?:website|site|project|app|application)",
  r"(?:please\s+)?make\s+(?:some\s+)?changes\s+(?:in|to|on)\s+"
  r"(?:that|this|the|my|our)\s+(?:website|site|project|app|application)",
)

MISSING_RENAME_TARGET_PATTERNS = (
  r"(?:i\s+)?(?:want|need|would\s+like)\s+to\s+(?:change|update|rename|rebrand)\s+"
  r"(?:the\s+)?(?:website|site|app|project)?\s*(?:name|title|brand)",
  r"(?:please\s+)?(?:change|update|rename|rebrand)\s+(?:the\s+)?"
  r"(?:website|site|app|project)?\s*(?:name|title|brand)",
)

GENERIC_FEATURE_REQUEST_PATTERNS = (
  r"(?:i\s+)?(?:want|need|would\s+like)\s+to\s+(?:add|create|include|implement|build|make)\s+"
  r"(?:(?:a|an|some|new|another)\s+){0,2}(?:feature|features|module|modules|page|pages|section|sections|"
  r"tab|tabs|integration|integrations|workflow|workflows|report|reports|screen|screens|"
  r"component|components)(?:\s+(?:in|to|on|for)\s+(?:that|this|the|my|our)\s+"
  r"(?:website|site|project|app|application|dashboard))?",
  r"(?:please\s+)?(?:add|create|include|implement|build|make)\s+"
  r"(?:(?:a|an|some|new|another)\s+){0,2}"
  r"(?:feature|features|module|modules|page|pages|section|sections|tab|tabs|integration|"
  r"integrations|workflow|workflows|report|reports|screen|screens|component|components)"
  r"(?:\s+(?:in|to|on|for)\s+(?:that|this|the|my|our)\s+"
  r"(?:website|site|project|app|application|dashboard))?",
)


def looks_like_underspecified_update_request(prompt: str) -> bool:
  normalized = re.sub(r"\s+", " ", str(prompt or "").strip().lower())
  normalized = re.sub(r"[.!?]+$", "", normalized).strip()
  return any(re.fullmatch(pattern, normalized) for pattern in UNDERSPECIFIED_UPDATE_PATTERNS)


def _normalize_prompt(prompt: str) -> str:
  normalized = re.sub(r"\s+", " ", str(prompt or "").strip().lower())
  return re.sub(r"[.!?]+$", "", normalized).strip()


def missing_update_requirements(prompt: str) -> dict[str, Any] | None:
  normalized = _normalize_prompt(prompt)
  if not normalized:
    return {
      "missing_fields": ["update_request"],
      "clarification_question": (
        "What exact change do you want to make? Mention the page, feature, or behavior "
        "you want updated."
      ),
    }
  if looks_like_underspecified_update_request(normalized):
    return {
      "missing_fields": ["target_page_or_component", "expected_change"],
      "clarification_question": (
        "What exactly would you like to modify? Please mention the page or "
        "component and the expected visual or functional change."
      ),
    }
  if any(re.fullmatch(pattern, normalized) for pattern in MISSING_RENAME_TARGET_PATTERNS):
    return {
      "missing_fields": ["new_name_or_brand_title"],
      "clarification_question": (
        "What new name should I use? Please share the exact website, app, or brand "
        "name you want applied."
      ),
    }
  if any(re.fullmatch(pattern, normalized) for pattern in GENERIC_FEATURE_REQUEST_PATTERNS):
    return {
      "missing_fields": ["feature_details", "target_area"],
      "clarification_question": (
        "Which feature do you want to add or change? Please mention the target page, "
        "module, or workflow and what it should do."
      ),
    }
  return None


def assess_request_understanding(
  prompt: str,
  *,
  intent: str,
) -> dict[str, Any]:
  """Central pre-execution completeness decision shared by every runtime surface."""
  if intent == "needs_more_detail":
    return {
      "actionable": False,
      "clarification_required": True,
      "operation": "needs_more_detail",
      "missing_fields": ["required_user_detail"],
      "clarification_question": "Please provide the missing detail needed to continue.",
      "decision_source": "shared_request_understanding",
    }
  if intent == "website_update" and looks_like_underspecified_update_request(prompt):
    missing = missing_update_requirements(prompt) or {}
    return {
      "actionable": False,
      "clarification_required": True,
      "operation": "website_update",
      "missing_fields": list(missing.get("missing_fields") or ["target_page_or_component", "expected_change"]),
      "clarification_question": str(
        missing.get("clarification_question")
        or "What exactly would you like to modify? Please mention the page or "
        "component and the expected visual or functional change."
      ),
      "decision_source": "shared_request_understanding",
    }
  if intent == "website_update":
    missing = missing_update_requirements(prompt)
    if missing is not None:
      return {
        "actionable": False,
        "clarification_required": True,
        "operation": "website_update",
        "missing_fields": list(missing.get("missing_fields") or []),
        "clarification_question": str(missing.get("clarification_question") or ""),
        "decision_source": "shared_request_understanding",
      }
  return {
    "actionable": True,
    "clarification_required": False,
    "operation": intent,
    "missing_fields": [],
    "clarification_question": "",
    "decision_source": "shared_request_understanding",
  }
