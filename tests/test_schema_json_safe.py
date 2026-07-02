from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from langgraph.types import Interrupt

from backend.llm.schema.json_safe import json_dumps_for_persistence, json_safe_value, sanitize_for_persistence
from backend.llm.schema.response import sanitize_generation_response


def test_json_safe_value_serializes_langgraph_interrupt():
  interrupt = Interrupt(
    {
      "type": "requirement_confirmation",
      "thread_id": "project-1:run-1",
      "brief": {"summary": "Build a storefront", "status": "pending"},
    }
  )

  payload = json_safe_value(interrupt)

  assert payload == {
    "type": "langgraph_interrupt",
    "interrupt_id": str(interrupt.id),
    "value": {
      "type": "requirement_confirmation",
      "thread_id": "project-1:run-1",
      "brief": {"summary": "Build a storefront", "status": "pending"},
    },
  }
  json.dumps(payload)


def test_sanitize_generation_response_strips_non_json_interrupt_from_orchestration_graph():
  interrupt = Interrupt({"type": "requirement_confirmation", "brief": {"summary": "Confirm work"}})
  result = {
    "multi_agent_system": {
      "intent": "needs_confirmation",
      "conversation_response": {"message": "Please confirm.", "confirmation": {"status": "pending"}},
    },
    "gemini_tool_calling_setup": {"tools": [{"name": "route_generation_action"}]},
    "google_adk_usage": {"adk_agents": [{"name": "Prompt Analyst Agent"}]},
    "orchestration_flow": {
      "generated_website": {
        "title": "Pending",
        "headline": "Pending",
        "subheadline": "Pending",
        "primary_cta": "Confirm",
        "secondary_cta": "Revise",
        "preview_html": "",
        "theme": {
          "colors": {
            "primary": "#111111",
            "secondary": "#222222",
            "accent": "#333333",
            "background": "#ffffff",
            "text": "#111111",
          },
          "style_direction": "Pending",
        },
        "sections": [{"name": "Hero", "purpose": "Intro", "content": "Pending", "items": ["One"]}],
        "files": [],
      }
    },
    "agent_to_agent_communication": {"message_contract": {"from_agent": "Router", "to_agent": "User"}},
    "proactive_thinking": {
      "recommended_next_actions": ["Confirm the execution brief."],
      "backend_execution": {
        "orchestration_graph": {
          "status": "interrupted",
          "interrupt": interrupt,
        }
      },
    },
  }

  sanitized = sanitize_generation_response(result)
  json.dumps(sanitized)
  assert sanitized["proactive_thinking"]["backend_execution"]["orchestration_graph"]["interrupt"]["type"] == "langgraph_interrupt"
  assert sanitized["proactive_thinking"]["backend_execution"]["orchestration_graph"]["interrupt"]["value"]["type"] == "requirement_confirmation"


def test_persistence_sanitizer_converts_known_objects_and_drops_runtime_values():
  @dataclass
  class ExampleData:
    name: str
    count: int

  class PydanticLike:
    def model_dump(self):
      return {"status": "ready"}

  class ProviderLike:
    name = "gemini"
    model = "gemini-test"
    provider_role = "artifact"

  class UnknownRuntimeObject:
    pass

  payload = sanitize_for_persistence(
    {
      "data": ExampleData("items", 3),
      "model_output": PydanticLike(),
      "provider_metadata": ProviderLike(),
      "unknown": UnknownRuntimeObject(),
      "provider": ProviderLike(),
    }
  )

  assert payload["data"] == {"name": "items", "count": 3}
  assert payload["model_output"] == {"status": "ready"}
  assert payload["provider_metadata"] == {
    "type": "ProviderLike",
    "name": "gemini",
    "model": "gemini-test",
    "provider_role": "artifact",
  }
  assert "unknown" not in payload
  assert "provider" not in payload
  json.loads(json_dumps_for_persistence(payload, context="test.persistence"))
