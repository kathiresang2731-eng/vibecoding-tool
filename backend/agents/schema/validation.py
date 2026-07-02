from __future__ import annotations

from typing import Any

from .constants import REQUIRED_NESTED_PATHS, REQUIRED_RESPONSE_SECTIONS
from .errors import ResponseContractError
from .helpers import get_nested_value


def validate_generation_shape(result: dict[str, Any]) -> None:
  if not isinstance(result, dict):
    raise ResponseContractError("LLM response must be a JSON object.")

  missing = [key for key in REQUIRED_RESPONSE_SECTIONS if key not in result]
  if missing:
    raise ResponseContractError(f"LLM response missing required sections: {', '.join(missing)}")

  for section in REQUIRED_RESPONSE_SECTIONS:
    if not isinstance(result[section], dict):
      raise ResponseContractError(f"LLM section must be an object: {section}")

  for path in REQUIRED_NESTED_PATHS:
    value = get_nested_value(result, path)
    if value is None:
      raise ResponseContractError(f"LLM response missing required nested path: {'.'.join(path)}")
    if isinstance(value, dict) and not value:
      raise ResponseContractError(f"LLM nested object cannot be empty: {'.'.join(path)}")
    if isinstance(value, list) and not value:
      raise ResponseContractError(f"LLM nested list cannot be empty: {'.'.join(path)}")
