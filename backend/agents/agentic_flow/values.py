from __future__ import annotations

from typing import Any


def object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def list_value(value: Any) -> list[Any]:
  return value if isinstance(value, list) else []


def text_value(value: Any, fallback: str) -> str:
  if isinstance(value, str) and value.strip():
    return value.strip()
  return fallback
