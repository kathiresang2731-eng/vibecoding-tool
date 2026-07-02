from __future__ import annotations

from typing import Any

from .artifact import build_artifact_steps
from .constants import AGENTIC_RUNTIME_NAME, AGENT_ROSTER
from .conversation import build_conversation_steps
from .handoffs import build_handoffs
from .memory import generation_memory_content
from .steps import agent_step
from .values import list_value, object_value, text_value


def execute_agentic_flow(response: dict[str, Any]) -> dict[str, Any]:
  from ..orchestration.legacy_response_trace import build_legacy_response_trace

  return build_legacy_response_trace(response)


__all__ = [
  "AGENTIC_RUNTIME_NAME",
  "AGENT_ROSTER",
  "execute_agentic_flow",
  "build_artifact_steps",
  "build_conversation_steps",
  "agent_step",
  "build_handoffs",
  "generation_memory_content",
  "object_value",
  "list_value",
  "text_value",
]
