from __future__ import annotations

from typing import Any

from .profiles import DOMAIN_CATEGORY_HINTS, DOMAIN_PROFILES, NO_SPECIFICATION_PHRASES


def infer_domain_key(text: str) -> str:
  lowered = text.lower()
  for domain_key, profile in DOMAIN_CATEGORY_HINTS.items():
    if any(keyword in lowered for keyword in profile["keywords"]):
      return domain_key
  return ""


def no_specification_prompt(prompt: str) -> bool:
  lowered = prompt.lower()
  return any(phrase in lowered for phrase in NO_SPECIFICATION_PHRASES)


def is_generic_value(value: Any, generic_values: set[str]) -> bool:
  if not isinstance(value, str):
    return True
  return value.strip().lower() in generic_values


def normalized_string_list(value: Any) -> list[str]:
  if not isinstance(value, list):
    return []
  return [str(item).strip() for item in value if str(item).strip()]


def is_generic_sections(sections: list[str]) -> bool:
  lowered = {section.lower() for section in sections}
  return not sections or lowered <= {"hero", "features", "contact", "services", "about"}
