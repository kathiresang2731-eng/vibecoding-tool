from __future__ import annotations

from typing import Any

from ..a2a_communication import CANONICAL_HANDOFF_REQUIRED_FIELDS
from .values import list_value


def a2a_contract_is_complete(a2a_runtime: dict[str, Any], handoffs: list[Any]) -> bool:
  messages = list_value(a2a_runtime.get("messages"))
  if not messages or not handoffs:
    return False
  candidates = [*messages, *handoffs]
  return all(isinstance(item, dict) and canonical_handoff_is_complete(item) for item in candidates)

def canonical_handoff_is_complete(item: dict[str, Any]) -> bool:
  for field in CANONICAL_HANDOFF_REQUIRED_FIELDS:
    if field not in item:
      return False
  confidence = item.get("confidence")
  return isinstance(confidence, (int, float)) and 0 <= confidence <= 1
