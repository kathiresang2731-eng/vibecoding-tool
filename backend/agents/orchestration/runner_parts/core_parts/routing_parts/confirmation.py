from __future__ import annotations

from typing import Any, Callable

from backend.agents.requirement_confirmation import (
  confirmation_conversation_response,
  confirmation_routing_result,
  confirmed_routing_result,
  evaluate_confirmation_reply,
  looks_like_confirmation_reply,
  persist_pending_confirmation,
  prepare_confirmation_brief,
  resolve_pending_confirmation,
  revised_request,
)
from backend.agents.schema import ResponseContractError


def process_confirmation_flow(
  *,
  orchestrator: Any,
  execution_prompt: str,
  pending_confirmation: dict[str, Any] | None,
  confirmation_action: str | None,
  control_client: Any,
  route_once: Callable[[str], dict[str, Any]],
  project_files_for_routing: Callable[[], list[dict[str, Any]]],
) -> dict[str, Any]:
  conversation_response_override: dict[str, Any] | None = None
  confirmation_brief: dict[str, Any] | None = None
  routing_result: dict[str, Any] | None = None
  confirmation_reply = confirmation_action in {"confirm", "cancel"} or looks_like_confirmation_reply(execution_prompt)

  if pending_confirmation and not confirmation_reply:
    orchestrator._emit_progress("routing.started", "Routing prompt through intent router")
    try:
      routing_result = route_once(execution_prompt)
    except ResponseContractError:
      routing_result = None
    else:
      from backend.debug_trace import trace_print

      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="route_generation_action_tool", intent=routing_result.get("intent"), next_action=routing_result.get("next_action"))
      if routing_result["intent"] == "simple_code":
        resolve_pending_confirmation(
          orchestrator.tool_context,
          orchestrator.user,
          project_id=orchestrator.project_id,
          pending=pending_confirmation,
          status="superseded",
        )
        orchestrator._emit_progress(
          "confirmation.decision.completed",
          "Pending execution brief superseded by standalone code request",
          status="completed",
          detail={"decision": "new_request", "superseded_by": "simple_code"},
        )
      else:
        routing_result = None
  elif pending_confirmation:
    routing_result = None

  if pending_confirmation and routing_result is None and confirmation_reply:
    orchestrator._emit_progress("confirmation.decision.started", "Checking the response to the pending execution brief")
    if confirmation_action == "confirm":
      decision = {"decision": "confirm", "revision": "", "reason": "Explicit confirm action from the workspace UI."}
    elif confirmation_action == "cancel":
      decision = {"decision": "cancel", "revision": "", "reason": "Explicit cancel action from the workspace UI."}
    else:
      decision = evaluate_confirmation_reply(control_client, execution_prompt, pending_confirmation)
    decision_name = decision["decision"]
    if decision_name == "confirm":
      if str(pending_confirmation.get("status") or "pending") == "pending":
        resolve_pending_confirmation(
          orchestrator.tool_context,
          orchestrator.user,
          project_id=orchestrator.project_id,
          pending=pending_confirmation,
          status="confirmed",
        )
      execution_prompt = str(
        pending_confirmation.get("effective_request")
        or pending_confirmation.get("original_request")
        or execution_prompt
      ).strip()
      confirmation_brief = dict(pending_confirmation)
      confirmation_store = getattr(orchestrator.tool_context, "store", None) if orchestrator.tool_context is not None else None
      routing_result = confirmed_routing_result(
        pending_confirmation,
        project_files=project_files_for_routing() if hasattr(confirmation_store, "list_files") else None,
      )
    elif decision_name == "revise":
      next_prompt = revised_request(pending_confirmation, execution_prompt, decision)
      revised_brief = prepare_confirmation_brief(
        control_client,
        next_prompt,
        operation=str(pending_confirmation.get("operation") or "website_generation"),
      )
      revised_brief["confirmation_required"] = True
      pending_confirmation = persist_pending_confirmation(
        orchestrator.tool_context,
        orchestrator.user,
        project_id=orchestrator.project_id,
        brief=revised_brief,
      )
      routing_result = confirmation_routing_result("The user revised the pending execution brief and must confirm the updated plan.")
      conversation_response_override = confirmation_conversation_response(pending_confirmation)
    elif decision_name == "cancel":
      resolve_pending_confirmation(
        orchestrator.tool_context,
        orchestrator.user,
        project_id=orchestrator.project_id,
        pending=pending_confirmation,
        status="cancelled",
      )
      cancelled_brief = {**pending_confirmation, "status": "cancelled"}
      routing_result = confirmation_routing_result("The user cancelled the pending execution brief.")
      conversation_response_override = confirmation_conversation_response(
        cancelled_brief,
        message="Cancelled the pending execution brief. No website files were changed.",
      )
    elif decision_name == "new_request":
      resolve_pending_confirmation(
        orchestrator.tool_context,
        orchestrator.user,
        project_id=orchestrator.project_id,
        pending=pending_confirmation,
        status="superseded",
      )
    else:
      routing_result = confirmation_routing_result("Explicit confirmation is still required before execution can start.")
      conversation_response_override = confirmation_conversation_response(
        pending_confirmation,
        message=f"I have not started the work because the execution brief is not confirmed yet.\n\n{confirmation_conversation_response(pending_confirmation)['message']}",
      )
    orchestrator._emit_progress(
      "confirmation.decision.completed",
      f"Confirmation response classified as {decision_name.replace('_', ' ')}",
      status="completed",
      detail={"decision": decision_name},
    )

  return {
    "execution_prompt": execution_prompt,
    "routing_result": routing_result,
    "conversation_response_override": conversation_response_override,
    "confirmation_brief": confirmation_brief,
    "pending_confirmation": pending_confirmation,
  }
