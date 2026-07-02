from __future__ import annotations

from typing import Any

from ..schema import sanitize_generation_response


def normalize_generation(result: dict[str, Any]) -> dict[str, Any]:
  return sanitize_generation_response(result)
