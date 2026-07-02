from __future__ import annotations

from typing import Any

from .missing import missing_conversation_provider_fields
from .scoring import add_check
from .values import int_value, list_value, object_value, text_value


def add_conversation_checks(
  checks: list[dict[str, Any]],
  *,
  runtime: dict[str, Any],
  tool_setup: dict[str, Any],
) -> None:
  tool_sequence = [item for item in list_value(tool_setup.get("tool_call_sequence")) if isinstance(item, str)]
  runtime_final_output = object_value(runtime.get("final_output"))
  artifact_provider = text_value(tool_setup.get("artifact_provider"))

  add_check(
    checks,
    name="conversation_control_plane",
    passed=tool_setup.get("provider") == "gemini-native-control-artifact"
    and bool(text_value(tool_setup.get("control_provider")))
    and (not artifact_provider or artifact_provider == "not-used"),
    detail="Conversation-only turns must stay on Gemini control and skip artifact generation.",
    missing=missing_conversation_provider_fields(tool_setup),
  )
  add_check(
    checks,
    name="conversation_tool_sequence",
    passed=tool_sequence in (
      ["route_generation_action", "handle_greeting"],
      ["route_generation_action", "request_website_details"],
      ["route_generation_action", "confirm_execution_brief"],
    ),
    detail=f"tools={', '.join(tool_sequence)}",
    missing=[] if len(tool_sequence) == 2 else ["gemini_tool_calling_setup.tool_call_sequence"],
  )
  add_check(
    checks,
    name="no_artifact_generation",
    passed=not any(name in tool_sequence for name in {"generate_website_files", "generate_project_artifact", "generate_update_artifact"})
    and int_value(runtime_final_output.get("file_count")) == 0,
    detail="Conversation branches must not generate, preview, or commit website files.",
    missing=[] if int_value(runtime_final_output.get("file_count")) == 0 else ["agentic_runtime.final_output.file_count == 0"],
  )
