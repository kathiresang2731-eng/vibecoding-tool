from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def slug(value: Any) -> str:
  return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def title_name(value: str) -> str:
  return f"{value.replace('_', ' ').title()} Agent"


def text_value(value: Any) -> str:
  return value.strip() if isinstance(value, str) else ""


def string_list(value: Any) -> list[str]:
  if not isinstance(value, list):
    return []
  return [str(item).strip() for item in value if str(item).strip()]


def object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
  return value if isinstance(value, list) else []


def unique_strings(values: list[str]) -> list[str]:
  seen: set[str] = set()
  unique: list[str] = []
  for value in values:
    if value and value not in seen:
      seen.add(value)
      unique.append(value)
  return unique


def parse_json_object(value: str) -> dict[str, Any]:
  text = value.strip()
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
  try:
    parsed = json.loads(text)
  except json.JSONDecodeError:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
      return {}
    try:
      parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
      return {}
  return parsed if isinstance(parsed, dict) else {}


def sha256_text(value: str) -> str:
  return hashlib.sha256(value.encode("utf-8")).hexdigest()
