from __future__ import annotations

from typing import Any, Iterable

from backend.debug_trace import trace_print

from backend.agents.patch_approval import patch_approval_conversation_response
from ..provider_utils import provider_name
from ..runtime_metadata import apply_backend_routing_to_response
from ..artifact_response import (
  build_website_generation_response,
  enrich_artifact_response_from_runtime,
  log_generated_website_tools,
)
from ..tool_registry import merge_tool_registry_entries, real_backend_tool_registry_entries


def finalize_runtime_generated_website(
  orchestrator: Any,
  state: Any,
  runtime_result: dict[str, Any],
  *,
  workflow_label: str,
  runtime_provider: str,
  trace_branch: str | None = None,
  tool_call_sequence: Iterable[str] | None = None,
  extra_self_checks: Iterable[str] | None = None,
  merge_backend_tools: bool = False,
  completion_progress: tuple[str, str, str] | None = None,
) -> dict[str, Any]:
  generated_website = runtime_result["generated_website"]
  state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
  state.response = build_website_generation_response(
    state,
    generated_website=generated_website,
    artifact_response=state.raw_llm_response,
  )
  state.response["multi_agent_system"]["agentic_runtime"] = runtime_result.get("runtime", {})

  if runtime_result.get("awaiting_patch_approval"):
    pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
    state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
    apply_backend_routing_to_response(state)
    orchestrator._emit_progress(
      "patch.approval.required",
      "Paused before commit — waiting for patch approval",
      status="running",
      detail={"patch_approval": pending},
    )
    trace_print(
      "EXIT",
      file=__file__,
      class_name="WorktualGenerationOrchestrator",
      function="orchestration_flow",
      branch="awaiting_patch_approval",
    )
    return state.response["orchestration_flow"]

  runtime = runtime_result.get("runtime") if isinstance(runtime_result.get("runtime"), dict) else {}
  runtime_status = str(runtime.get("status") or "completed")
  state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
    "runtime_status": runtime_status,
    "provider": runtime_provider,
    "model": provider_name(state.artifact_client),
    "tool_calls": runtime.get("tool_calls", []),
    "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
  }
  if tool_call_sequence is not None:
    state.response["gemini_tool_calling_setup"]["tool_call_sequence"] = list(tool_call_sequence)
  if merge_backend_tools:
    state.response["gemini_tool_calling_setup"]["tools"] = merge_tool_registry_entries(
      state.response["gemini_tool_calling_setup"].get("tools", []),
      real_backend_tool_registry_entries(),
    )
  if extra_self_checks is not None:
    state.response["proactive_thinking"]["self_checks"] = [
      *state.response["proactive_thinking"].get("self_checks", []),
      *list(extra_self_checks),
    ]

  apply_backend_routing_to_response(state)
  log_generated_website_tools(state.response)
  if completion_progress is not None:
    step, message, status = completion_progress
    if runtime_status == "failed":
      orchestrator._emit_progress(
        "agent.runtime.failed",
        str(runtime.get("output_text") or "Agent runtime failed before producing a file patch."),
        status="failed",
        detail={"runtime_status": runtime_status, "changed_paths": runtime.get("changed_paths") or []},
      )
    else:
      orchestrator._emit_progress(step, message, status=status)
  trace_print(
    "EXIT",
    file=__file__,
    class_name="WorktualGenerationOrchestrator",
    function="orchestration_flow",
    branch=trace_branch or workflow_label,
  )
  return state.response["orchestration_flow"]
