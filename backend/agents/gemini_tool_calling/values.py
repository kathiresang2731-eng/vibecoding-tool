from __future__ import annotations

from typing import Any


def string_value(value: Any) -> str:
  return value.strip() if isinstance(value, str) else ""
