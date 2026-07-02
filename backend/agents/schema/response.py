from __future__ import annotations

from typing import Any

from .constants import REQUIRED_RESPONSE_SECTIONS
from .json_safe import json_safe_value
from .validation import validate_generation_shape


def empty_generation_response() -> dict[str, Any]:
  return {
    "multi_agent_system": {},
    "gemini_tool_calling_setup": {},
    "google_adk_usage": {},
    "orchestration_flow": {},
    "agent_to_agent_communication": {},
    "proactive_thinking": {},
  }


def sanitize_generation_response(result: dict[str, Any]) -> dict[str, Any]:
  validate_generation_shape(result)
  sanitized = {section: result[section] for section in REQUIRED_RESPONSE_SECTIONS}
  return json_safe_value(sanitized)
