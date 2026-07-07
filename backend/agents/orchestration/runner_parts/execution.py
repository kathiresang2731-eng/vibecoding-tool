from __future__ import annotations

from typing import Any

from backend.debug_trace import trace_print

from ..provider_utils import default_control_provider, is_artifact_intent
from ..conversation import build_conversation_generation_response, generate_conversation_response
from backend.agents.schema import ResponseContractError
from .document_artifact import handle_document_artifact_branch
from .legacy_fallback import handle_legacy_fallback_branch
from .simple_code import handle_simple_code_branch
from .website_runtime import handle_website_runtime_branch


def execute_orchestration_flow(orchestrator: Any, state: Any) -> dict[str, Any]:
  trace_print("ENTER", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", intent=state.intent, project_id=orchestrator.project_id or "-")
  execution_plan = {}
  try:
    execution_plan = ((state.routing_result.get("orchestrator_brain") or {}).get("execution_plan") or {})
  except Exception:
    execution_plan = {}
  if execution_plan.get("mutation_allowed") is False and is_artifact_intent(state.intent):
    orchestrator._emit_progress(
      "orchestrator.mutation_guard.blocked",
      "Execution plan blocked artifact mutation for this answer-only request",
      status="completed",
      detail=execution_plan,
    )
    state.intent = "project_info" if execution_plan.get("query_class") == "answer_only" else "needs_more_detail"
    state.routing_result["intent"] = state.intent
    state.routing_result["next_tool"] = "answer_question" if state.intent == "project_info" else "request_website_details"

  if not is_artifact_intent(state.intent):
    client = state.control_client or default_control_provider()
    orchestrator._emit_progress("conversation.response", "Preparing assistant reply for this non-generation request")
    conversation_response = generate_conversation_response(state, client)
    state.response = build_conversation_generation_response(state, conversation_response)
    orchestrator._emit_progress("conversation.response.completed", "Assistant reply prepared", status="completed")
    trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="conversation")
    return state.response["orchestration_flow"]

  if state.intent == "simple_code":
    return handle_simple_code_branch(orchestrator, state)

  if state.intent == "document_artifact":
    return handle_document_artifact_branch(orchestrator, state)

  runtime_result = handle_website_runtime_branch(orchestrator, state)
  if runtime_result is not None:
    return runtime_result

  if not orchestrator.allow_legacy_fallback:
    raise ResponseContractError("Website generation requires project_id, tool_context, and user for the real agent runtime.")

  return handle_legacy_fallback_branch(orchestrator, state)
