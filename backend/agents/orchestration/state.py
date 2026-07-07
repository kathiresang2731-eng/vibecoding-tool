from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class GenerationPipelineState:
  user_prompt: str
  intent: str = "website_generation"
  routing_result: dict[str, Any] = field(default_factory=dict)
  control_client: Any | None = None
  artifact_client: Any | None = None
  prepared_sections: dict[str, Any] = field(default_factory=dict)
  stage_trace: list[dict[str, Any]] = field(default_factory=list)
  orchestration_trace: dict[str, Any] = field(default_factory=dict)
  raw_llm_response: dict[str, Any] | None = None
  response: dict[str, Any] | None = None
  conversation_response_override: dict[str, Any] | None = None
  attachments: list[dict[str, Any]] = field(default_factory=list)
  adaptive_route: dict[str, Any] = field(default_factory=dict)
  confirmation_brief: dict[str, Any] | None = None

