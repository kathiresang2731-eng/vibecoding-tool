from __future__ import annotations

from typing import Any


def missing_required_fields(value: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
  return [field for field in fields if field not in value]

def object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}

def list_value(value: Any) -> list[Any]:
  return value if isinstance(value, list) else []

def text_value(value: Any) -> str:
  return value.strip() if isinstance(value, str) else ""

def int_value(value: Any) -> int:
  return value if isinstance(value, int) else 0
