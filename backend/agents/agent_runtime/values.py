from __future__ import annotations

from typing import Any


def text_or_default(value: Any, fallback: str) -> str:
  return value.strip() if isinstance(value, str) and value.strip() else fallback


def string_list(value: Any, fallback: list[str]) -> list[str]:
  if isinstance(value, list):
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if normalized:
      return normalized
  return fallback


def list_value(value: Any) -> list[Any]:
  return value if isinstance(value, list) else []


def object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}
