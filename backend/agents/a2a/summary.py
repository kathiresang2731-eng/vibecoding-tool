from __future__ import annotations

from typing import Any

from .constants import CANONICAL_HANDOFF_REQUIRED_FIELDS


def build_a2a_summary(a2a_runtime: dict[str, Any]) -> dict[str, Any]:
  return {
    "protocol": a2a_runtime["protocol"],
    "runtime": a2a_runtime["runtime"],
    "branch": a2a_runtime["branch"],
    "message_count": a2a_runtime["message_count"],
    "ack_count": a2a_runtime["ack_count"],
    "validation_status": a2a_runtime["validation"]["status"],
    "handoff_contract_fields": list(a2a_runtime.get("handoff_contract_fields") or CANONICAL_HANDOFF_REQUIRED_FIELDS),
  }
