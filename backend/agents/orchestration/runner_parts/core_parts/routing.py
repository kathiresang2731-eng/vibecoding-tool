from __future__ import annotations

from typing import Any

from backend.agents.followup_routing import apply_existing_project_routing_bias
from backend.agents.chat_history import (
  prior_rename_target_suggestion,
  prior_rename_target_suggestion_from_memories,
  recover_update_clarification_prompt,
  enrich_same_topic_referential_prompt,
)
from backend.agents.prompt_context import current_user_prompt
from backend.agents.project_workspace import is_vite_scaffold_complete, meaningful_project_source_files
from backend.agents.project_inspection import (
  build_project_inspection_context,
  build_target_resolution,
  clarification_for_ambiguous_update_target,
)
from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  classify_adaptive_request_route,
)
from backend.agents.request_understanding import assess_request_understanding
from backend.agents.memory.topic_clustering import filter_chat_messages_for_topic
from backend.agents.requirement_confirmation import (
  confirmation_conversation_response,
  confirmation_enabled,
  confirmation_routing_result,
  persist_pending_confirmation,
  load_pending_confirmation,
  load_retryable_confirmation,
  looks_like_confirmation_reply,
  prepare_confirmation_brief,
  resolve_pending_confirmation,
)
from backend.agents.schema import ResponseContractError
from backend.debug_trace import trace_print
from backend.agents.orchestration.brain import build_orchestrator_brain
from backend.agents.orchestration.routing import route_generation_action_tool
from .routing_parts.adaptive import resolve_adaptive_route
from .routing_parts.confirmation import process_confirmation_flow


_MODEL_UNAVAILABLE_UPDATE_MARKERS = (
  "update",
  "change",
  "add",
  "remove",
  "replace",
  "fix",
  "edit",
  "modify",
  "button",
  "click",
  "clicked",
  "popup",
  "pop up",
  "modal",
  "not working",
  "navigate",
  "route",
  "redirect",
)


def _routing_model_key_missing(exc: Exception) -> bool:
  lowered = str(exc or "").lower()
  return "missing gemini_api_key" in lowered or "gemini_api_key in .env" in lowered


def _looks_like_existing_project_update(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  return bool(lowered) and any(marker in lowered for marker in _MODEL_UNAVAILABLE_UPDATE_MARKERS)


def build_routing_context(
  orchestrator: Any,
  user_prompt: str,
  *,
  confirmation_action: str | None,
  control_client: Any,
  artifact_client: Any,
) -> dict[str, Any]:
  raw_prompt = user_prompt.strip()
  if not raw_prompt and not orchestrator.attachments:
    raise ValueError("Prompt is empty. Describe the website you want to build or attach a screenshot/file.")
  execution_prompt = current_user_prompt(raw_prompt) or raw_prompt

  def _chat_messages_for_routing() -> list[dict[str, Any]]:
    store = getattr(orchestrator.tool_context, "store", None) if orchestrator.tool_context is not None else None
    if (
      not orchestrator.project_id
      or store is None
      or orchestrator.user is None
      or not hasattr(store, "list_project_chat_messages")
    ):
      return []
    try:
      return store.list_project_chat_messages(
        orchestrator.project_id,
        orchestrator.user,
        limit=20,
        chat_session_id=orchestrator.chat_session_id,
        chat_topic_id=getattr(orchestrator, "chat_topic_id", None),
      )
    except TypeError as exc:
      if "chat_session_id" not in str(exc) and "chat_topic_id" not in str(exc):
        return []
      try:
        messages = store.list_project_chat_messages(
          orchestrator.project_id,
          orchestrator.user,
          limit=20,
          chat_session_id=orchestrator.chat_session_id,
        )
        return filter_chat_messages_for_topic(
          messages,
          chat_topic_id=getattr(orchestrator, "chat_topic_id", None),
        )
      except Exception:
        return []
    except Exception:
      return []

  recovered_prompt = recover_update_clarification_prompt(execution_prompt, _chat_messages_for_routing())
  if recovered_prompt != execution_prompt:
    execution_prompt = recovered_prompt
    orchestrator._emit_progress(
      "routing.update_clarification_resumed",
      "Recovered the pending website update from the latest clarification reply",
      status="completed",
      detail={"source": "chat_session_followup"},
    )
  same_topic_prompt = enrich_same_topic_referential_prompt(execution_prompt, _chat_messages_for_routing())
  if same_topic_prompt != execution_prompt:
    execution_prompt = same_topic_prompt
    orchestrator._emit_progress(
      "routing.same_topic_continuity",
      "Resolved same-topic referential follow-up before intent routing",
      status="completed",
      detail={"source": "chat_topic_history"},
    )
  initial_execution_prompt = execution_prompt
  orchestrator.initial_execution_prompt = initial_execution_prompt

  def _project_files_for_routing() -> list[dict[str, Any]]:
    if not orchestrator.project_id or orchestrator.tool_context is None or orchestrator.user is None:
      return []
    try:
      return orchestrator.tool_context.store.list_files(orchestrator.project_id, orchestrator.user)
    except Exception:
      return []

  def _episodic_memories_for_routing() -> list[dict[str, Any]]:
    store = getattr(orchestrator.tool_context, "store", None) if orchestrator.tool_context is not None else None
    if (
      not orchestrator.project_id
      or store is None
      or orchestrator.user is None
      or not orchestrator.chat_session_id
    ):
      return []
    try:
      from backend.agents.memory.episodic import select_episodic_memories_for_prompt

      return select_episodic_memories_for_prompt(
        store,
        orchestrator.user,
        project_id=orchestrator.project_id,
        prompt=execution_prompt,
        chat_session_id=orchestrator.chat_session_id,
        chat_topic_id=getattr(orchestrator, "chat_topic_id", None),
        limit=4,
      )
    except Exception:
      return []

  def _finalize_routing(routing: dict[str, Any]) -> dict[str, Any]:
    return apply_existing_project_routing_bias(
      routing,
      prompt=execution_prompt,
      project_files=_project_files_for_routing(),
    )

  routing_cache: dict[str, dict[str, Any]] = {}

  def _route_once(prompt: str) -> dict[str, Any]:
    route_key = current_user_prompt(prompt).strip() or prompt.strip()
    cached = routing_cache.get(route_key)
    if cached is not None:
      return dict(cached)
    try:
      routed = _finalize_routing(route_generation_action_tool(prompt, control_client))
    except ResponseContractError as exc:
      if not _routing_model_key_missing(exc):
        raise
      project_files = _project_files_for_routing()
      understanding = assess_request_understanding(prompt, intent="website_update")
      if (
        meaningful_project_source_files(project_files)
        and is_vite_scaffold_complete(project_files)
        and _looks_like_existing_project_update(prompt)
      ):
        if understanding.get("clarification_required") is True:
          routed = {
            "intent": "needs_more_detail",
            "next_action": "request_website_details",
            "next_tool": "request_website_details",
            "reason": "Control model is unavailable; the update request still needs required details.",
            "request_understanding": understanding,
          }
        else:
          routed = {
            "intent": "website_update",
            "next_action": "update_website",
            "next_tool": "analyze_update_request",
            "reason": "Control model key is missing; existing project files and the current request indicate a scoped website update.",
            "request_understanding": understanding,
            "decision_source": "existing_project_update_fallback",
          }
          adaptive_probe = classify_adaptive_request_route(
            prompt,
            intent="website_update",
            project_files=project_files,
            attachments=orchestrator.attachments,
          )
          if adaptive_probe.route not in {
            ADAPTIVE_ROUTE_TARGETED_UPDATE,
            ADAPTIVE_ROUTE_FEATURE_UPDATE,
            ADAPTIVE_ROUTE_LARGE_PROJECT,
          }:
            raise
        orchestrator._emit_progress(
          "routing.model_unavailable_fallback",
          "Control model key is missing; continuing as an existing-project website update",
          status="completed",
          detail={
            "code": "routing_control_model_key_missing",
            "intent": routed.get("intent"),
            "decision_source": routed.get("decision_source") or "request_understanding",
          },
        )
      else:
        raise
    routing_cache[route_key] = dict(routed)
    return routed

  routing_result: dict[str, Any] | None = None
  conversation_response_override: dict[str, Any] | None = None
  confirmation_brief: dict[str, Any] | None = None
  pending_confirmation = load_pending_confirmation(orchestrator.tool_context, orchestrator.user, project_id=orchestrator.project_id) if orchestrator.project_id else None
  if confirmation_action == "confirm" and not pending_confirmation and orchestrator.project_id:
    pending_confirmation = load_retryable_confirmation(orchestrator.tool_context, orchestrator.user, project_id=orchestrator.project_id)
  if pending_confirmation:
    confirmation_state = process_confirmation_flow(
      orchestrator=orchestrator,
      execution_prompt=execution_prompt,
      pending_confirmation=pending_confirmation,
      confirmation_action=confirmation_action,
      control_client=control_client,
      route_once=_route_once,
      project_files_for_routing=_project_files_for_routing,
    )
    execution_prompt = confirmation_state["execution_prompt"]
    routing_result = confirmation_state["routing_result"]
    conversation_response_override = confirmation_state["conversation_response_override"]
    confirmation_brief = confirmation_state["confirmation_brief"]
    pending_confirmation = confirmation_state["pending_confirmation"]

  if routing_result is None:
    orchestrator._emit_progress("routing.started", "Routing prompt through intent router")
    routing_result = _route_once(execution_prompt)
    trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="route_generation_action_tool", intent=routing_result.get("intent"), next_action=routing_result.get("next_action"))
    understanding = routing_result.get("request_understanding") if isinstance(routing_result, dict) else {}
    missing_fields = {
      str(item).strip()
      for item in (understanding.get("missing_fields") or [])
      if str(item).strip()
    } if isinstance(understanding, dict) else set()
    if (
      routing_result.get("intent") == "needs_more_detail"
      and "new_name_or_brand_title" in missing_fields
      and conversation_response_override is None
    ):
      suggested_name = prior_rename_target_suggestion(execution_prompt, _chat_messages_for_routing())
      suggestion_source = "chat_session_followup"
      if not suggested_name:
        suggested_name = prior_rename_target_suggestion_from_memories(
          execution_prompt,
          _episodic_memories_for_routing(),
        )
        suggestion_source = "episodic_memory"
      if suggested_name:
        conversation_response_override = {
          "type": "needs_more_detail",
          "message": (
            f'Previously you mentioned "{suggested_name}". '
            "Do you want to use that name, or provide a different one?"
          ),
          "received_message": execution_prompt,
          "routing_result": routing_result,
          "next_prompt_guidance": [
            f'Use "{suggested_name}"',
            "Provide a different website name",
            "Mention where the name should be updated",
          ],
        }
        orchestrator._emit_progress(
          "routing.resume_hint.ready",
          "Recovered the previously provided website name as a restart suggestion",
          status="completed",
          detail={"suggested_name": suggested_name, "source": suggestion_source},
        )
    if (
      pending_confirmation
      and routing_result.get("intent")
      not in {"greeting", "needs_more_detail", "needs_confirmation"}
    ):
      resolve_pending_confirmation(
        orchestrator.tool_context,
        orchestrator.user,
        project_id=orchestrator.project_id,
        pending=pending_confirmation,
        status="superseded",
      )
      pending_confirmation = None
    skip_update_confirmation = (
      routing_result["intent"] == "website_update"
      and bool(meaningful_project_source_files(_project_files_for_routing()))
    )
    if (
      routing_result["intent"] in {"website_generation", "website_update"}
      and not skip_update_confirmation
      and confirmation_enabled(orchestrator.tool_context, project_id=orchestrator.project_id, user=orchestrator.user)
      and confirmation_action != "confirm"
      and not looks_like_confirmation_reply(execution_prompt)
    ):
      orchestrator._emit_progress("confirmation.brief.started", "Preparing an execution brief for confirmation")
      operation = str(routing_result["intent"])
      brief = prepare_confirmation_brief(
        control_client,
        execution_prompt,
        operation=operation,
      )
      if brief["confirmation_required"]:
        pending_confirmation = persist_pending_confirmation(
          orchestrator.tool_context,
          orchestrator.user,
          project_id=orchestrator.project_id,
          brief=brief,
        )
        routing_result = confirmation_routing_result("The execution brief requires explicit user confirmation before work starts.")
        conversation_response_override = confirmation_conversation_response(pending_confirmation)
        orchestrator._emit_progress(
          "confirmation.brief.completed",
          "Prepared execution brief and paused before generation",
          status="completed",
          detail={"risk_level": brief["risk_level"], "operation": brief["operation"]},
        )

  project: dict[str, Any] = {}
  store = getattr(orchestrator.tool_context, "store", None) if orchestrator.tool_context is not None else None
  if orchestrator.project_id and orchestrator.user is not None and hasattr(store, "get_project"):
    try:
      project = store.get_project(orchestrator.project_id, orchestrator.user) or {}
    except Exception:
      project = {}
  routing_project_files = _project_files_for_routing()
  routing_chat_messages = _chat_messages_for_routing()
  routing_result["target_resolution"] = build_target_resolution(
    execution_prompt,
    routing_project_files,
    chat_messages=routing_chat_messages,
  )
  if routing_result.get("intent") == "website_update":
    clarification = clarification_for_ambiguous_update_target(
      execution_prompt,
      routing_project_files,
      target_resolution=routing_result.get("target_resolution"),
    )
    if isinstance(clarification, dict):
      routing_result = {
        "intent": "needs_more_detail",
        "next_action": "request_website_details",
        "next_tool": "request_website_details",
        "reason": "The target page was resolved, but the specific button and expected behavior still need clarification before editing files.",
        "request_understanding": {
          "actionable": False,
          "clarification_required": True,
          "operation": "website_update",
          "missing_fields": list(clarification.get("missing_fields") or ["button_identifier", "expected_behavior"]),
          "clarification_question": str(clarification.get("clarification_question") or "").strip(),
          "decision_source": "target_resolution_ambiguity_guard",
        },
        "target_resolution": routing_result.get("target_resolution") or {},
      }
  if routing_result.get("intent") == "project_info":
    routing_result["project_context"] = build_project_inspection_context(
      routing_project_files,
      question=execution_prompt,
      project_name=str(project.get("name") or ""),
      local_path=str(project.get("local_path") or ""),
      chat_messages=routing_chat_messages,
    )
    routing_result["target_resolution"] = (
      routing_result["project_context"].get("target_resolution")
      or routing_result["target_resolution"]
    )

  orchestrator._emit_progress(
    "routing.completed",
    f"Intent router selected {routing_result['intent'].replace('_', ' ')}",
    status="completed",
    detail=routing_result,
  )
  adaptive_route = resolve_adaptive_route(
    orchestrator=orchestrator,
    initial_execution_prompt=initial_execution_prompt,
    execution_prompt=execution_prompt,
    routing_result=routing_result,
    project_files_for_routing=_project_files_for_routing,
  )
  routing_result["adaptive_route"] = adaptive_route
  orchestrator_brain = build_orchestrator_brain(
    prompt=execution_prompt,
    routing_result=routing_result,
    adaptive_route=adaptive_route,
    project_files=_project_files_for_routing(),
  )
  routing_result["orchestrator_brain"] = orchestrator_brain
  orchestrator._emit_progress(
    "routing.adaptive.completed",
    f"Adaptive route selected {str(adaptive_route.get('route') or 'unknown').replace('_', ' ')}",
    status="completed",
    detail=adaptive_route,
  )
  orchestrator._emit_progress(
    "orchestrator.brain.ready",
    "Main orchestrator brain selected the query policy and agentic capabilities",
    status="completed",
    detail=orchestrator_brain,
  )
  orchestrator._emit_progress(
    "orchestrator.execution_plan.ready",
    "Main orchestrator selected the execution path for this query",
    status="completed",
    detail=orchestrator_brain.get("execution_plan") or {},
  )
  orchestrator._emit_progress(
    "orchestrator.target_resolved",
    "Main orchestrator resolved the page, file, or UI element for this query",
    status="completed",
    detail=routing_result.get("target_resolution") or {},
  )
  try:
    from backend.orchestration_terminal import print_routing_result
  except ImportError:
    from orchestration_terminal import print_routing_result
  print_routing_result(routing_result)
  orchestrator._emit_progress(
    "route.intent",
    f"Routed as {routing_result.get('intent')}",
    status="completed",
    detail=routing_result,
  )
  return {
    "execution_prompt": execution_prompt,
    "routing_result": routing_result,
    "conversation_response_override": conversation_response_override,
    "confirmation_brief": confirmation_brief,
    "adaptive_route": adaptive_route,
    "pending_confirmation": pending_confirmation,
  }
