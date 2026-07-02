from __future__ import annotations

import json
import time
from typing import Any, Callable

try:
  from ...debug_trace import trace_function, trace_print
except ImportError:
  from debug_trace import trace_function, trace_print
from ..adk_mapping import format_adk_mapping_for_prompt, get_adk_mapping
from ..agent_runtime_loop import execute_real_agent_runtime_loop
from ..domain_research import build_domain_research_context
from ..graph_runtime.orchestration_graph import execute_langgraph_orchestration
from ..orchestration_graph import execute_orchestration_stage_graph
from ..runtime_config import (
  langgraph_runtime_default,
  langgraph_website_runtime_enabled,
  parallel_stream_orchestrator_enabled,
  parallel_website_generation_default,
  should_use_parallel_website_workflow,
  runtime_engine,
  streaming_fast_path_enabled,
  streaming_file_agent_enabled,
  unified_website_updates_active,
)
from ..providers import (
  ARTIFACT_PROVIDER_ROLE,
  CONTROL_PROVIDER_ROLE,
  GeminiProvider,
  LLMProvider,
  assert_provider_role,
)
from ..requirement_confirmation import (
  confirmation_conversation_response,
  confirmation_enabled,
  confirmation_routing_result,
  confirmed_routing_result,
  evaluate_confirmation_reply,
  load_pending_confirmation,
  load_retryable_confirmation,
  looks_like_confirmation_reply,
  persist_pending_confirmation,
  prepare_confirmation_brief,
  resolve_pending_confirmation,
  revised_request,
)
from ..patch_approval import patch_approval_conversation_response
from ..prompt_context import current_user_prompt
from ..project_workspace import meaningful_project_source_files, standalone_code_source_files
from ..prompts import SIMPLE_CODE_SYSTEM_INSTRUCTION, build_simple_code_prompt, build_website_prompt
from ..prompts import build_minimal_simple_code_prompt
from ..request_complexity import (
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_SMALL_CODE,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  classify_adaptive_request_route,
)
from ..schema import ResponseContractError, sanitize_generation_response
from .artifact_response import (
  build_website_generation_response,
  enrich_artifact_response_from_runtime,
  log_generated_website_tools,
  normalize_generated_website_artifact,
  normalize_simple_code_artifact,
)
from .constants import DEFAULT_AGENT_TEAM, DEFAULT_TOOL_REGISTRY, PIPELINE_STAGE_ORDER
from .conversation import build_conversation_generation_response, generate_conversation_response
from .provider_utils import configured_adk_model, default_control_provider, is_artifact_intent, provider_name
from .routing import route_generation_action_tool
from ..followup_routing import apply_existing_project_routing_bias
from .live_runtime_trace import attach_live_runtime_metadata
from .runtime_metadata import (
  apply_backend_routing_to_response,
  existing_agentic_runtime,
  format_stage_name,
  require_pipeline_response,
  summarize_stage_output,
)
from .state import GenerationPipelineState
from .tool_registry import log_tool_call, merge_tool_registry_entries, real_backend_tool_registry_entries
from ..streaming.file_agent import is_error_repair_prompt, run_streaming_file_agent

_SIMPLE_CODE_CONTEXT_FILE_LIMIT = 4
_SIMPLE_CODE_CONTEXT_CHAR_LIMIT = 16_000
_SIMPLE_CODE_EXISTING_CONTEXT_MARKERS = (
  "this code",
  "existing code",
  "current code",
  "above code",
  "previous code",
  "change ",
  "update ",
  "modify ",
  "edit ",
  "fix ",
  "debug ",
  "simplify",
  "simplified",
  "convert ",
  "rewrite ",
  "refactor ",
  "remove ",
  "delete ",
  "without comments",
  "remove comments",
  "add comments",
)


def _existing_standalone_code_context(files: list[dict[str, Any]] | None) -> list[dict[str, str]]:
  context_files: list[dict[str, str]] = []
  used_chars = 0
  for item in standalone_code_source_files(files)[:_SIMPLE_CODE_CONTEXT_FILE_LIMIT]:
    path = str(item.get("path") or "").strip()
    content = item.get("content")
    if content is None:
      content = item.get("code")
    text = content if isinstance(content, str) else ""
    remaining = max(_SIMPLE_CODE_CONTEXT_CHAR_LIMIT - used_chars, 0)
    if remaining <= 0:
      break
    snippet = text[:remaining]
    used_chars += len(snippet)
    context_files.append({"path": path, "content": snippet})
  return context_files


def _should_include_existing_simple_code_context(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  if not lowered:
    return False
  return any(marker in lowered for marker in _SIMPLE_CODE_EXISTING_CONTEXT_MARKERS)


def _compatibility_export(name: str, fallback: Any) -> Any:
  try:
    from .. import orchestrator as compatibility_orchestrator

    return getattr(compatibility_orchestrator, name, fallback)
  except Exception:
    return fallback


class WorktualGenerationOrchestrator:
  @trace_function(project_id=lambda _self, **kwargs: kwargs.get("project_id") or "-", legacy=lambda _self, **kwargs: kwargs.get("allow_legacy_fallback", False))
  def __init__(
    self,
    *,
    llm_provider: LLMProvider | None = None,
    gemini_client: Any | None = None,
    control_provider: LLMProvider | None = None,
    artifact_provider: LLMProvider | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    project_id: str | None = None,
    tool_context: Any | None = None,
    user: Any | None = None,
    allow_legacy_fallback: bool = False,
    agent_run_id: str | None = None,
    graph_thread_id: str | None = None,
    resume_graph: bool = False,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  chat_session_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  adaptive_route: dict[str, Any] | None = None,
) -> None:
    self.llm_provider = llm_provider
    self.gemini_client = gemini_client
    self.control_provider = control_provider
    self.artifact_provider = artifact_provider
    self.progress_callback = progress_callback
    self.project_id = project_id
    self.tool_context = tool_context
    self.user = user
    self.allow_legacy_fallback = allow_legacy_fallback
    self.agent_run_id = agent_run_id
    self.graph_thread_id = graph_thread_id
    self.resume_graph = resume_graph
    self.confirmation_action = confirmation_action if confirmation_action in {"confirm", "cancel"} else None
    self.attachments = list(attachments or [])
    self.chat_session_id = chat_session_id
    self.project_name = project_name
    self.patch_action = patch_action if patch_action in {"approve", "reject"} else None
    self.adaptive_route = dict(adaptive_route or {})

  def run(
    self,
    user_prompt: str,
    *,
    confirmation_action: str | None = None,
  ) -> dict[str, Any]:
    trace_print("ENTER", file=__file__, class_name="WorktualGenerationOrchestrator", function="run", project_id=self.project_id or "-")
    started_at = time.monotonic()
    active_action = confirmation_action if confirmation_action in {"confirm", "cancel"} else self.confirmation_action
    try:
      return self._run_traced(user_prompt, confirmation_action=active_action)
    except Exception as exc:
      trace_print("ERROR", file=__file__, class_name="WorktualGenerationOrchestrator", function="run", duration_ms=round((time.monotonic() - started_at) * 1000, 2), error=str(exc)[:180])
      raise
    finally:
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="run", duration_ms=round((time.monotonic() - started_at) * 1000, 2))

  def _run_traced(
    self,
    user_prompt: str,
    *,
    confirmation_action: str | None = None,
  ) -> dict[str, Any]:
    raw_prompt = user_prompt.strip()
    if not raw_prompt and not self.attachments:
      raise ValueError("Prompt is empty. Describe the website you want to build or attach a screenshot/file.")
    execution_prompt = current_user_prompt(raw_prompt) or raw_prompt
    initial_execution_prompt = execution_prompt

    def _project_files_for_routing() -> list[dict[str, Any]]:
      if not self.project_id or self.tool_context is None or self.user is None:
        return []
      try:
        return self.tool_context.store.list_files(self.project_id, self.user)
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
      routed = _finalize_routing(route_generation_action_tool(prompt, control_client))
      routing_cache[route_key] = dict(routed)
      return routed

    control_client = self._resolve_control_provider()
    artifact_client = self._resolve_artifact_provider()
    trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="resolve_providers", control=provider_name(control_client), artifact=provider_name(artifact_client))
    routing_result: dict[str, Any] | None = None
    conversation_response_override: dict[str, Any] | None = None
    confirmation_brief: dict[str, Any] | None = None
    pending_confirmation = load_pending_confirmation(self.tool_context, self.user, project_id=self.project_id) if self.project_id else None
    if confirmation_action == "confirm" and not pending_confirmation and self.project_id:
      pending_confirmation = load_retryable_confirmation(self.tool_context, self.user, project_id=self.project_id)
    confirmation_reply = (
      confirmation_action in {"confirm", "cancel"}
      or looks_like_confirmation_reply(execution_prompt)
    )
    if pending_confirmation and not confirmation_reply:
      self._emit_progress("routing.started", "Routing prompt through intent router")
      try:
        routing_result = _route_once(execution_prompt)
      except ResponseContractError:
        routing_result = None
      else:
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="route_generation_action_tool", intent=routing_result.get("intent"), next_action=routing_result.get("next_action"))
        if routing_result["intent"] == "simple_code":
          resolve_pending_confirmation(
            self.tool_context,
            self.user,
            project_id=self.project_id,
            pending=pending_confirmation,
            status="superseded",
          )
          self._emit_progress(
            "confirmation.decision.completed",
            "Pending execution brief superseded by standalone code request",
            status="completed",
            detail={"decision": "new_request", "superseded_by": "simple_code"},
          )
        else:
          routing_result = None
      decision_name = ""
    elif pending_confirmation:
      routing_result = None
      decision_name = ""
    if pending_confirmation and routing_result is None and confirmation_reply:
      self._emit_progress("confirmation.decision.started", "Checking the response to the pending execution brief")
      if confirmation_action == "confirm":
        decision = {
          "decision": "confirm",
          "revision": "",
          "reason": "Explicit confirm action from the workspace UI.",
        }
      elif confirmation_action == "cancel":
        decision = {
          "decision": "cancel",
          "revision": "",
          "reason": "Explicit cancel action from the workspace UI.",
        }
      else:
        decision = evaluate_confirmation_reply(control_client, execution_prompt, pending_confirmation)
      decision_name = decision["decision"]
      if decision_name == "confirm":
        if str(pending_confirmation.get("status") or "pending") == "pending":
          resolve_pending_confirmation(
            self.tool_context,
            self.user,
            project_id=self.project_id,
            pending=pending_confirmation,
            status="confirmed",
          )
        execution_prompt = str(
          pending_confirmation.get("effective_request")
          or pending_confirmation.get("original_request")
          or execution_prompt
        ).strip()
        confirmation_brief = dict(pending_confirmation)
        confirmation_store = getattr(self.tool_context, "store", None) if self.tool_context is not None else None
        routing_result = confirmed_routing_result(
          pending_confirmation,
          project_files=_project_files_for_routing() if hasattr(confirmation_store, "list_files") else None,
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
          self.tool_context,
          self.user,
          project_id=self.project_id,
          brief=revised_brief,
        )
        routing_result = confirmation_routing_result("The user revised the pending execution brief and must confirm the updated plan.")
        conversation_response_override = confirmation_conversation_response(pending_confirmation)
      elif decision_name == "cancel":
        resolve_pending_confirmation(
          self.tool_context,
          self.user,
          project_id=self.project_id,
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
          self.tool_context,
          self.user,
          project_id=self.project_id,
          pending=pending_confirmation,
          status="superseded",
        )
      else:
        routing_result = confirmation_routing_result("Explicit confirmation is still required before execution can start.")
        conversation_response_override = confirmation_conversation_response(
          pending_confirmation,
          message=f"I have not started the work because the execution brief is not confirmed yet.\n\n{confirmation_conversation_response(pending_confirmation)['message']}",
        )
      self._emit_progress(
        "confirmation.decision.completed",
        f"Confirmation response classified as {decision_name.replace('_', ' ')}",
        status="completed",
        detail={"decision": decision_name},
      )

    if routing_result is None:
      self._emit_progress("routing.started", "Routing prompt through intent router")
      routing_result = _route_once(execution_prompt)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="route_generation_action_tool", intent=routing_result.get("intent"), next_action=routing_result.get("next_action"))
      if pending_confirmation and routing_result.get("intent") in {
        "website_update",
        "website_generation",
        "project_info",
        "simple_code",
      }:
        resolve_pending_confirmation(
          self.tool_context,
          self.user,
          project_id=self.project_id,
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
        and confirmation_enabled(self.tool_context, project_id=self.project_id, user=self.user)
        and confirmation_action != "confirm"
        and not looks_like_confirmation_reply(execution_prompt)
      ):
        self._emit_progress("confirmation.brief.started", "Preparing an execution brief for confirmation")
        operation = str(routing_result["intent"])
        if operation == "website_update":
          try:
            from ..project_workspace import is_greenfield_generation
          except ImportError:
            try:
              from backend.agents.project_workspace import is_greenfield_generation
            except ImportError:
              from agents.project_workspace import is_greenfield_generation
          confirmation_store = getattr(self.tool_context, "store", None) if self.tool_context is not None else None
          if hasattr(confirmation_store, "list_files") and is_greenfield_generation(intent="website_generation", files=_project_files_for_routing()):
            operation = "website_generation"
        brief = prepare_confirmation_brief(
          control_client,
          execution_prompt,
          operation=operation,
        )
        if brief["confirmation_required"]:
          pending_confirmation = persist_pending_confirmation(
            self.tool_context,
            self.user,
            project_id=self.project_id,
            brief=brief,
          )
          routing_result = confirmation_routing_result("The execution brief requires explicit user confirmation before work starts.")
          conversation_response_override = confirmation_conversation_response(pending_confirmation)
          self._emit_progress(
            "confirmation.brief.completed",
            "Prepared execution brief and paused before generation",
            status="completed",
            detail={"risk_level": brief["risk_level"], "operation": brief["operation"]},
          )
    self._emit_progress(
      "routing.completed",
      f"Intent router selected {routing_result['intent'].replace('_', ' ')}",
      status="completed",
      detail=routing_result,
    )
    restored_confirmed_request = execution_prompt != initial_execution_prompt
    if restored_confirmed_request:
      adaptive_route = classify_adaptive_request_route(
        execution_prompt,
        intent=routing_result.get("intent"),
        project_files=_project_files_for_routing(),
        attachments=self.attachments,
      ).to_dict()
      adaptive_route["reclassified_after_confirmation"] = True
    else:
      final_adaptive_route = classify_adaptive_request_route(
        execution_prompt,
        intent=routing_result.get("intent"),
        project_files=_project_files_for_routing(),
        attachments=self.attachments,
      ).to_dict()
      preflight_route = self.adaptive_route or {}
      preflight_route_name = str(preflight_route.get("route") or "")
      final_route_name = str(final_adaptive_route.get("route") or "")
      if (
        preflight_route_name in {ADAPTIVE_ROUTE_FULL_GENERATION, ADAPTIVE_ROUTE_LARGE_PROJECT}
        and final_route_name in {ADAPTIVE_ROUTE_SMALL_CODE, ADAPTIVE_ROUTE_TARGETED_UPDATE, ADAPTIVE_ROUTE_FEATURE_UPDATE}
      ):
        adaptive_route = final_adaptive_route
        adaptive_route["reclassified_after_final_intent"] = True
        adaptive_route["previous_preflight_route"] = preflight_route_name
      else:
        adaptive_route = preflight_route or final_adaptive_route
    routing_result["adaptive_route"] = adaptive_route
    self._emit_progress(
      "routing.adaptive.completed",
      f"Adaptive route selected {str(adaptive_route.get('route') or 'unknown').replace('_', ' ')}",
      status="completed",
      detail=adaptive_route,
    )
    try:
      from ...orchestration_terminal import print_routing_result
    except ImportError:
      from orchestration_terminal import print_routing_result
    print_routing_result(routing_result)
    self._emit_progress(
      "route.intent",
      f"Routed as {routing_result.get('intent')}",
      status="completed",
      detail=routing_result,
    )

    state = GenerationPipelineState(
      user_prompt=execution_prompt,
      intent=routing_result["intent"],
      routing_result=routing_result,
      control_client=control_client,
      artifact_client=artifact_client,
      conversation_response_override=conversation_response_override,
      attachments=list(self.attachments),
      adaptive_route=adaptive_route,
      confirmation_brief=confirmation_brief,
    )

    stage_handlers: dict[str, Callable[[GenerationPipelineState], dict[str, Any]]] = {
      "multi_agent_system": self.multi_agent_system,
      "gemini_tool_calling_setup": self.gemini_tool_calling_setup,
      "google_adk_usage": self.google_adk_usage,
      "orchestration_flow": self.orchestration_flow,
      "agent_to_agent_communication": self.agent_to_agent_communication,
      "proactive_thinking": self.proactive_thinking,
    }

    orchestration_executor = execute_orchestration_stage_graph
    use_langgraph_orchestration = (
      runtime_engine() == "langgraph"
      and not (
        streaming_file_agent_enabled()
        and routing_result.get("intent") in {"website_generation", "website_update"}
      )
    )
    if use_langgraph_orchestration:
      orchestration_executor = execute_langgraph_orchestration
    graph_thread_id = self.graph_thread_id
    if not graph_thread_id and self.project_id and self.agent_run_id:
      graph_thread_id = f"{self.project_id}:{self.agent_run_id}"
    executor_kwargs: dict[str, Any] = {
      "intent": state.intent,
      "routing_result": state.routing_result,
      "execute_stage": lambda stage_name: self._execute_stage(stage_name, stage_handlers[stage_name], state),
      "emit_progress": lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
    }
    if orchestration_executor is execute_langgraph_orchestration:
      executor_kwargs["orchestration_state"] = {
        "intent": state.intent,
        "routing_result": state.routing_result,
        "pending_confirmation": pending_confirmation if state.intent == "needs_confirmation" else None,
        "thread_id": graph_thread_id,
      }
      if graph_thread_id:
        executor_kwargs["checkpointer_context"] = {
          "store": getattr(self.tool_context, "store", None),
          "user": self.user,
          "agent_run_id": self.agent_run_id,
          "project_id": self.project_id,
          "thread_id": graph_thread_id,
        }
      executor_kwargs["resume_graph"] = self.resume_graph
    state.orchestration_trace = orchestration_executor(**executor_kwargs)

    if state.orchestration_trace.get("status") == "interrupted" and state.response is None:
      for stage_name in ("orchestration_flow", "agent_to_agent_communication", "proactive_thinking"):
        self._execute_stage(stage_name, stage_handlers[stage_name], state)
      state.orchestration_trace["status"] = "completed_after_interrupt"

    if state.response is None:
      raise ResponseContractError("Generation pipeline completed without a response.")

    try:
      attach_live_runtime_metadata(
        state.response,
        user_prompt=state.user_prompt,
        routing_result=state.routing_result,
      )
      state.response["proactive_thinking"]["backend_execution"]["orchestration_graph"] = state.orchestration_trace
    except Exception as exc:
      projection_error = {
        "status": "skipped",
        "reason": str(exc)[:1200],
        "source_of_truth_runtime_preserved": bool(existing_agentic_runtime(state.response)),
      }
      state.response["proactive_thinking"].setdefault("backend_execution", {})["runtime_projection_error"] = projection_error
      self._emit_progress(
        "runtime.projection.failed",
        "Runtime projection metadata failed after generation; preserving generated files and preview",
        status="failed",
        detail=projection_error,
      )

    self._emit_progress("response.normalizing", "Normalizing final generation response")
    return sanitize_generation_response(state.response)

  def _resolve_control_provider(self) -> Any:
    provider = self.control_provider or self.llm_provider or default_control_provider()
    assert_provider_role(provider, CONTROL_PROVIDER_ROLE)
    return provider

  def _resolve_artifact_provider(self) -> Any:
    provider = self.artifact_provider or self.gemini_client or self.llm_provider or GeminiProvider()
    assert_provider_role(provider, ARTIFACT_PROVIDER_ROLE)
    return provider

  def _emit_progress(
    self,
    step: str,
    message: str,
    *,
    status: str = "running",
    detail: dict[str, Any] | None = None,
    audit_detail: dict[str, Any] | None = None,
  ) -> None:
    if not self.progress_callback:
      return
    try:
      self.progress_callback(
        {
          "step": step,
          "message": message,
          "status": status,
          "detail": detail or {},
        }
      )
    except Exception:
      pass

  def _execute_stage(
    self,
    stage_name: str,
    handler: Callable[[GenerationPipelineState], dict[str, Any]],
    state: GenerationPipelineState,
  ) -> None:
    started_at = time.time()
    self._emit_progress(
      f"stage.{stage_name}.started",
      f"Running {format_stage_name(stage_name)}",
    )
    try:
      output = handler(state)
      duration_ms = round((time.time() - started_at) * 1000)
      summary = summarize_stage_output(output)
      state.stage_trace.append(
        {
          "stage": stage_name,
          "status": "completed",
          "duration_ms": duration_ms,
          "summary": summary,
        }
      )
      self._emit_progress(
        f"stage.{stage_name}.completed",
        f"Completed {format_stage_name(stage_name)}",
        status="completed",
        detail={"duration_ms": duration_ms, "summary": summary},
      )
      if stage_name == "proactive_thinking" and state.response is not None:
        state.response["proactive_thinking"]["backend_execution"]["completed_stages"] = [
          entry for entry in state.stage_trace if entry["status"] == "completed"
        ]
    except Exception:
      duration_ms = round((time.time() - started_at) * 1000)
      state.stage_trace.append(
        {
          "stage": stage_name,
          "status": "failed",
          "duration_ms": duration_ms,
        }
      )
      self._emit_progress(
        f"stage.{stage_name}.failed",
        f"Failed during {format_stage_name(stage_name)}",
        status="failed",
        detail={"duration_ms": duration_ms},
      )
      raise

  def multi_agent_system(self, state: GenerationPipelineState) -> dict[str, Any]:
    is_greeting = state.intent == "greeting"
    needs_more_detail = state.intent == "needs_more_detail"
    needs_confirmation = state.intent == "needs_confirmation"
    is_simple_code = state.intent == "simple_code"
    is_update = state.intent == "website_update"
    active_agent = (
      "Greeting Handler Agent"
      if is_greeting
      else "Requirement Confirmation Agent"
      if needs_confirmation
      else "Simple Code Writer Agent"
      if is_simple_code
      else "Intent Router Agent"
      if needs_more_detail
      else "Prompt Analyst Agent"
    )
    section = {
      "goal": (
        "Handle a greeting and collect the website brief."
        if is_greeting
        else "Present the execution brief and wait for explicit user confirmation."
        if needs_confirmation
        else "Ask for more website details before generation."
        if needs_more_detail
        else "Write a standalone code file directly from the user prompt."
        if is_simple_code
        else "Update the existing website from the user prompt."
        if is_update
        else "Generate a complete website from the user prompt."
      ),
      "intent": state.intent,
      "agents": DEFAULT_AGENT_TEAM,
      "active_agent": active_agent,
      "routing_result": state.routing_result,
      "conversation_response": {},
      "shared_state": {
        "prompt": state.user_prompt,
        "project_context": (
          "Greeting received; waiting for website description."
          if is_greeting
          else "Execution brief prepared; waiting for explicit user confirmation."
          if needs_confirmation
          else "More details needed before generation."
          if needs_more_detail
          else "Standalone code request; code artifact generation is selected."
          if is_simple_code
          else "Existing project update requested; pending update analysis."
          if is_update
          else "Pending prompt analysis"
        ),
        "website_blueprint": (
          "Not started until the user describes the website."
          if is_greeting or needs_more_detail
          else "Waiting for user confirmation before execution."
          if needs_confirmation
          else "No website blueprint needed for a standalone code file."
          if is_simple_code
          else "Pending update plan"
          if is_update
          else "Pending predictive planning"
        ),
        "generated_files": (
          "No website files generated before explicit confirmation."
          if not is_artifact_intent(state.intent)
          else "Pending standalone code artifact"
          if is_simple_code
          else "Pending updated project artifact"
          if is_update
          else "Pending orchestration output"
        ),
        "validation_report": (
          "Conversation turn handled before generation validation."
          if not is_artifact_intent(state.intent)
          else "Pending code artifact validation."
          if is_simple_code
          else "Pending diagnostic checks"
        ),
      },
    }
    state.prepared_sections["multi_agent_system"] = section
    return section

  def gemini_tool_calling_setup(self, state: GenerationPipelineState) -> dict[str, Any]:
    if state.intent == "greeting":
      tool_sequence = ["route_generation_action", "handle_greeting"]
    elif state.intent == "needs_more_detail":
      tool_sequence = ["route_generation_action", "request_website_details"]
    elif state.intent == "needs_confirmation":
      tool_sequence = ["route_generation_action", "confirm_execution_brief"]
    elif state.intent == "simple_code":
      tool_sequence = ["route_generation_action", "generate_simple_code_file", "validate_generated_website"]
    elif state.intent == "website_update":
      tool_sequence = [
        "route_generation_action",
        "READ_PROJECT_FILES",
        "LOAD_PROJECT_MEMORY",
        "analyze_update_request",
        "generate_update_artifact",
        "validate_generated_website",
      ]
    else:
      tool_sequence = [
        "route_generation_action",
        "analyze_prompt",
        "generate_website_files",
        "validate_generated_website",
      ]
    section = {
      "tool_policy": (
        "Gemini classifies chat/routing turns, can request backend tools through native function calling, and generates website artifacts."
      ),
      "provider": "gemini-native-control-artifact",
      "control_provider": provider_name(state.control_client),
      "artifact_provider": provider_name(state.artifact_client),
      "native_tool_calling": {
        "status": "enabled",
        "mode": "VALIDATED",
        "safety_boundary": "Python validates tool order, arguments, preview readiness, and file commits.",
      },
      "tools": DEFAULT_TOOL_REGISTRY,
      "tool_call_sequence": tool_sequence,
    }
    log_tool_call(
      "tool_calling_setup",
      "sequence",
      {
        "intent": state.intent,
        "tool_call_sequence": tool_sequence,
      },
    )
    state.prepared_sections["gemini_tool_calling_setup"] = section
    return section

  def google_adk_usage(self, state: GenerationPipelineState) -> dict[str, Any]:
    section = get_adk_mapping()
    section["adk_agents"] = [
      {
        "adk_type": "LlmAgent",
        "name": "intent_router_agent",
        "purpose": "Calls the routing tool that selects greeting handling, detail collection, or website generation.",
      },
      {
        "adk_type": "AgentTool",
        "name": "route_generation_action_tool",
        "purpose": "Callable routing tool used before any website generation action.",
      },
      {
        "adk_type": "LlmAgent",
        "name": "greeting_handler_agent",
        "purpose": "Responds to turns routed as greeting and asks for the website brief before generation.",
      },
      {
        "adk_type": "AgentTool",
        "name": "handle_greeting_tool",
        "purpose": "Callable greeting response tool used by the orchestrator before website generation.",
      },
      {
        "adk_type": "LlmAgent",
        "name": "simple_code_writer_agent",
        "purpose": "Generates standalone code files directly for simple_code turns.",
      },
      {
        "adk_type": "AgentTool",
        "name": "generate_simple_code_file_tool",
        "purpose": "Callable code artifact generator used when the router selects simple_code.",
      },
      *section["adk_agents"],
    ]
    state.prepared_sections["google_adk_usage"] = section
    return section

  def orchestration_flow(self, state: GenerationPipelineState) -> dict[str, Any]:
    trace_print("ENTER", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", intent=state.intent, project_id=self.project_id or "-")
    if not is_artifact_intent(state.intent):
      client = state.control_client or default_control_provider()
      self._emit_progress("conversation.response", "Preparing assistant reply for this non-generation request")
      conversation_response = generate_conversation_response(state, client)
      state.response = build_conversation_generation_response(state, conversation_response)
      self._emit_progress("conversation.response.completed", "Assistant reply prepared", status="completed")
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="conversation")
      return state.response["orchestration_flow"]

    if state.intent == "simple_code":
      existing_project_files: list[dict[str, Any]] = []
      if self.project_id and self.tool_context is not None and self.user is not None:
        store = getattr(self.tool_context, "store", None)
        if store is not None and hasattr(store, "list_files"):
          try:
            existing_project_files = store.list_files(self.project_id, self.user)
          except Exception:
            existing_project_files = []
      include_existing_code_context = _should_include_existing_simple_code_context(state.user_prompt)
      existing_code_files = _existing_standalone_code_context(existing_project_files) if include_existing_code_context else []
      learned_preferences = ""
      if self.tool_context is not None and self.user is not None:
        try:
          from ..memory.context import build_user_preferences_context_block

          learned_preferences = build_user_preferences_context_block(
            getattr(self.tool_context, "store", None),
            self.user,
            prompt=state.user_prompt,
            limit=6,
          )
        except Exception:
          learned_preferences = ""
      adaptive_route = state.adaptive_route or {}
      simple_code_context = {
        "routing_result": state.routing_result,
        "adaptive_route": adaptive_route,
        "selected_agent": "Simple Code Writer Agent",
        "selected_action": "write_standalone_code_file",
        "workflow": "simple_code_model_artifact",
        "existing_standalone_files": existing_code_files,
        "existing_context_included": include_existing_code_context,
        "learned_preferences": learned_preferences,
        "code_update_policy": (
          "If the user asks to change, simplify, convert, fix, or update existing standalone code, "
          "use existing_standalone_files as the target context and return only the changed standalone code file(s)."
        ),
      }
      prompt_builder = (
        build_minimal_simple_code_prompt
        if adaptive_route.get("route") == ADAPTIVE_ROUTE_SMALL_CODE
        else build_simple_code_prompt
      )
      prompt = prompt_builder(state.user_prompt, pipeline_context=json.dumps(simple_code_context, indent=2))
      client = state.artifact_client or GeminiProvider()
      self._emit_progress(
        "agent.decision",
        "Chief Orchestrator selected the Simple Code Writer Agent for this request",
        status="completed",
        detail={
          "intent": "simple_code",
          "selected_agent": "Simple Code Writer Agent",
          "selected_action": "write_standalone_code_file",
          "decision_source": "model_chief_orchestrator",
          "decision_reason": state.routing_result.get("reason"),
          "workflow": "simple_code_model_artifact",
          "adaptive_route": adaptive_route,
          "existing_code_files": [item["path"] for item in existing_code_files],
          "existing_context_included": include_existing_code_context,
          "learned_preferences_included": bool(learned_preferences),
        },
      )
      self._emit_progress("generate_simple_code_file.input", "Sending standalone code request to the artifact model")
      state.raw_llm_response = client.generate_json(
        prompt,
        system_instruction=SIMPLE_CODE_SYSTEM_INSTRUCTION,
        trace_label="generate_simple_code_file",
        max_output_tokens=4096,
        chat_history=[],
      )
      self._emit_progress("generate_simple_code_file.output", "Artifact model returned standalone code files", status="completed")
      self._emit_progress("artifact.validation", "Validating generated code file artifact")
      generated_website = normalize_simple_code_artifact(state.raw_llm_response)
      self._emit_progress(
        "artifact.validated",
        f"Validated {len(generated_website.get('files') or [])} generated code files",
        status="completed",
        detail={
          "file_count": len(generated_website.get("files") or []),
          "paths": [
            file_item.get("path")
            for file_item in generated_website.get("files") or []
            if isinstance(file_item, dict)
          ],
        },
      )
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="simple_code")
      return state.response["orchestration_flow"]

    website_intents = {"website_generation", "website_update"}
    store = getattr(self.tool_context, "store", None) if self.tool_context is not None else None
    runtime_ready = (
      self.project_id
      and self.tool_context is not None
      and self.user is not None
      and hasattr(store, "list_files")
    )
    adaptive_route = state.adaptive_route or {}
    adaptive_route_name = str(adaptive_route.get("route") or "").strip()
    if (
      unified_website_updates_active()
      and state.intent == "website_update"
      and runtime_ready
      and streaming_file_agent_enabled()
    ):
      use_parallel_stream_for_website = False
      use_streaming_single_agent = True
      use_langgraph_for_website = False
    else:
      prefer_streaming_error_repair = (
        state.intent == "website_update"
        and is_error_repair_prompt(state.user_prompt)
      )
      use_parallel_stream_for_website = (
        runtime_ready
        and state.intent in website_intents
        and streaming_file_agent_enabled()
        and parallel_stream_orchestrator_enabled()
        and parallel_website_generation_default()
        and adaptive_route_name in {ADAPTIVE_ROUTE_LARGE_PROJECT, ADAPTIVE_ROUTE_FULL_GENERATION}
        and should_use_parallel_website_workflow(intent=state.intent, prompt=state.user_prompt)
        and not prefer_streaming_error_repair
      )
      use_streaming_single_agent = (
        runtime_ready
        and state.intent in website_intents
        and streaming_file_agent_enabled()
        and not use_parallel_stream_for_website
        and (
          adaptive_route_name in {ADAPTIVE_ROUTE_TARGETED_UPDATE, ADAPTIVE_ROUTE_FEATURE_UPDATE}
          or state.intent == "website_update"
          or streaming_fast_path_enabled()
          or prefer_streaming_error_repair
        )
      )
      use_langgraph_for_website = (
        runtime_ready
        and state.intent in website_intents
        and langgraph_website_runtime_enabled()
        and not use_parallel_stream_for_website
        and not use_streaming_single_agent
      )
    if state.intent == "website_update":
      try:
        from ...visual_qa import ensure_update_visual_baseline

        ensure_update_visual_baseline(
          project_id=self.project_id,
          user=self.user,
          tool_context=self.tool_context,
          prompt=state.user_prompt,
          chat_session_id=self.chat_session_id,
          agent_run_id=self.agent_run_id,
          emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        )
      except Exception as exc:
        self._emit_progress(
          "automation.baseline.failed",
          f"Before-update screenshot baseline check failed: {exc}",
          status="failed",
          detail={"error": str(exc)},
        )

    if (
      state.intent == "website_generation"
      and runtime_ready
      and streaming_file_agent_enabled()
    ):
      from ..generation_engine.greenfield_runner import run_website_generation

      self._emit_progress(
        "agent.decision",
        "Using greenfield generation engine for new website build",
        status="completed",
        detail={
          "intent": state.intent,
          "selected_agent": "Greenfield Generation Engine",
          "workflow": "greenfield_generation",
        },
      )
      runtime_result = run_website_generation(
        project_id=self.project_id,
        user=self.user,
        tool_context=self.tool_context,
        prompt=state.user_prompt,
        artifact_provider=state.artifact_client or GeminiProvider(),
        emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        attachments=state.attachments,
        chat_session_id=self.chat_session_id,
        project_name=self.project_name,
        patch_action=self.patch_action,
        agent_run_id=self.agent_run_id,
        confirmation_brief=state.confirmation_brief,
      )
      workflow_label = str((runtime_result.get("runtime") or {}).get("workflow") or "greenfield_generation")
      if runtime_result.get("awaiting_patch_approval"):
        generated_website = runtime_result["generated_website"]
        pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
        state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
        state.response = build_website_generation_response(
          state,
          generated_website=generated_website,
          artifact_response=state.raw_llm_response,
        )
        state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
        state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
        apply_backend_routing_to_response(state)
        self._emit_progress(
          "patch.approval.required",
          "Paused before commit — waiting for patch approval",
          status="running",
          detail={"patch_approval": pending},
        )
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="awaiting_patch_approval")
        return state.response["orchestration_flow"]
      generated_website = runtime_result["generated_website"]
      state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
      state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
        "runtime_status": "completed",
        "provider": workflow_label,
        "model": provider_name(state.artifact_client),
        "tool_calls": runtime_result["runtime"].get("tool_calls", []),
        "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
      }
      state.response["gemini_tool_calling_setup"]["tool_call_sequence"] = [
        "plan_greenfield_tasks",
        "greenfield_generation",
        "read_file",
        "list_files",
        "write_file",
        "str_replace",
        "WRITE_PROJECT_FILES",
      ]
      state.response["gemini_tool_calling_setup"]["tools"] = merge_tool_registry_entries(
        state.response["gemini_tool_calling_setup"].get("tools", []),
        real_backend_tool_registry_entries(),
      )
      state.response["proactive_thinking"]["self_checks"] = [
        *state.response["proactive_thinking"].get("self_checks", []),
        f"Files were written through the {workflow_label}",
      ]
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch=workflow_label)
      return state.response["orchestration_flow"]

    if use_parallel_stream_for_website:
      from ..streaming.parallel_orchestrator import run_parallel_stream_orchestrator

      self._emit_progress(
        "orchestrator.starting",
        "Planning parallel file workers and starting multi-agent generation",
        status="running",
        detail={"intent": state.intent, "workflow": "parallel_stream_orchestrator"},
      )
      runtime_result = run_parallel_stream_orchestrator(
        project_id=self.project_id,
        user=self.user,
        tool_context=self.tool_context,
        prompt=state.user_prompt,
        intent=state.intent,
        artifact_provider=state.artifact_client or GeminiProvider(),
        emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        attachments=state.attachments,
        chat_session_id=self.chat_session_id,
        project_name=self.project_name,
        patch_action=self.patch_action,
      )
      workflow_label = "parallel_stream_orchestrator"
      if runtime_result.get("awaiting_patch_approval"):
        generated_website = runtime_result["generated_website"]
        pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
        state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
        state.response = build_website_generation_response(
          state,
          generated_website=generated_website,
          artifact_response=state.raw_llm_response,
        )
        state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
        state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
        apply_backend_routing_to_response(state)
        self._emit_progress(
          "patch.approval.required",
          "Paused before commit — waiting for patch approval",
          status="running",
          detail={"patch_approval": pending},
        )
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="awaiting_patch_approval")
        return state.response["orchestration_flow"]
      generated_website = runtime_result["generated_website"]
      state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
      state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
        "runtime_status": "completed",
        "provider": workflow_label,
        "model": provider_name(state.artifact_client),
        "tool_calls": runtime_result["runtime"].get("tool_calls", []),
        "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
      }
      state.response["gemini_tool_calling_setup"]["tool_call_sequence"] = [
        "plan_file_work",
        "parallel_file_workers",
        "agent.parallel.wave",
        "read_file",
        "list_files",
        "write_file",
        "str_replace",
        "WRITE_PROJECT_FILES",
      ]
      state.response["gemini_tool_calling_setup"]["tools"] = merge_tool_registry_entries(
        state.response["gemini_tool_calling_setup"].get("tools", []),
        real_backend_tool_registry_entries(),
      )
      state.response["proactive_thinking"]["self_checks"] = [
        *state.response["proactive_thinking"].get("self_checks", []),
        f"Files were written through the {workflow_label}",
      ]
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch=workflow_label)
      return state.response["orchestration_flow"]

    if use_langgraph_for_website:
      self._emit_progress(
        "agent.runtime.loop.started",
        "Starting LangGraph agent runtime (default path)",
        status="running",
        detail={"intent": state.intent, "workflow": "langgraph_runtime_default"},
      )
      execute_real_agent_runtime_loop_fn = _compatibility_export(
        "execute_real_agent_runtime_loop",
        execute_real_agent_runtime_loop,
      )
      runtime_result = execute_real_agent_runtime_loop_fn(
        project_id=self.project_id,
        user=self.user,
        tool_context=self.tool_context,
        prompt=state.user_prompt,
        routing_result=state.routing_result,
        control_provider=state.control_client or default_control_provider(),
        artifact_provider=state.artifact_client or GeminiProvider(),
        prepared_sections=state.prepared_sections,
        emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        agent_run_id=self.agent_run_id,
        graph_thread_id=self.graph_thread_id or (f"{self.project_id}:{self.agent_run_id}" if self.project_id and self.agent_run_id else None),
        resume_graph=self.resume_graph,
        chat_session_id=self.chat_session_id,
        project_name=self.project_name,
        patch_action=self.patch_action,
      )
      if runtime_result.get("awaiting_patch_approval"):
        generated_website = runtime_result["generated_website"]
        pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
        state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
        state.response = build_website_generation_response(
          state,
          generated_website=generated_website,
          artifact_response=state.raw_llm_response,
        )
        state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
        state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
        apply_backend_routing_to_response(state)
        self._emit_progress(
          "patch.approval.required",
          "Paused before commit — waiting for patch approval",
          status="running",
          detail={"patch_approval": pending},
        )
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="awaiting_patch_approval")
        return state.response["orchestration_flow"]
      generated_website = runtime_result["generated_website"]
      state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
      state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
        "runtime_status": "completed",
        "provider": "langgraph_runtime_default",
        "model": provider_name(state.artifact_client),
        "tool_calls": runtime_result["runtime"].get("tool_calls", []),
        "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
      }
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="langgraph_runtime_default")
      return state.response["orchestration_flow"]

    if use_streaming_single_agent:
      self._emit_progress("agent.decision", "Using fast streaming file agent for this request", status="completed", detail={
        "intent": state.intent,
        "selected_agent": "Streaming File Agent",
        "selected_action": "streaming_file_agent",
        "decision_source": "streaming_file_agent_fast_path",
        "workflow": "streaming_file_agent",
      })
      runtime_result = run_streaming_file_agent(
        project_id=self.project_id,
        user=self.user,
        tool_context=self.tool_context,
        prompt=state.user_prompt,
        intent=state.intent,
        artifact_provider=state.artifact_client or GeminiProvider(),
        emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        attachments=state.attachments,
        chat_session_id=self.chat_session_id,
        project_name=self.project_name,
        patch_action=self.patch_action,
        agent_run_id=self.agent_run_id,
      )
      workflow_label = "streaming_file_agent"
      if runtime_result.get("awaiting_patch_approval"):
        generated_website = runtime_result["generated_website"]
        pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
        state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
        state.response = build_website_generation_response(
          state,
          generated_website=generated_website,
          artifact_response=state.raw_llm_response,
        )
        state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
        state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
        apply_backend_routing_to_response(state)
        self._emit_progress(
          "patch.approval.required",
          "Paused before commit — waiting for patch approval",
          status="running",
          detail={"patch_approval": pending},
        )
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="awaiting_patch_approval")
        return state.response["orchestration_flow"]
      generated_website = runtime_result["generated_website"]
      state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
      state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
        "runtime_status": "completed",
        "provider": workflow_label,
        "model": provider_name(state.artifact_client),
        "tool_calls": runtime_result["runtime"].get("tool_calls", []),
        "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
      }
      state.response["gemini_tool_calling_setup"]["tool_call_sequence"] = [
        "plan_file_work",
        "parallel_file_workers",
        "agent.parallel.wave",
        "read_file",
        "list_files",
        "write_file",
        "str_replace",
        "WRITE_PROJECT_FILES",
      ]
      state.response["gemini_tool_calling_setup"]["tools"] = merge_tool_registry_entries(
        state.response["gemini_tool_calling_setup"].get("tools", []),
        real_backend_tool_registry_entries(),
      )
      state.response["proactive_thinking"]["self_checks"] = [
        *state.response["proactive_thinking"].get("self_checks", []),
        f"Files were written through the {workflow_label}",
      ]
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch=workflow_label)
      return state.response["orchestration_flow"]

    if self.project_id and self.tool_context is not None and self.user is not None:
      self._emit_progress("agent.runtime.loop.started", "Starting real agent/tool runtime loop")
      execute_real_agent_runtime_loop_fn = _compatibility_export(
        "execute_real_agent_runtime_loop",
        execute_real_agent_runtime_loop,
      )
      runtime_result = execute_real_agent_runtime_loop_fn(
        project_id=self.project_id,
        user=self.user,
        tool_context=self.tool_context,
        prompt=state.user_prompt,
        routing_result=state.routing_result,
        control_provider=state.control_client or default_control_provider(),
        artifact_provider=state.artifact_client or GeminiProvider(),
        prepared_sections=state.prepared_sections,
        emit_progress=lambda step, message, **kwargs: self._emit_progress(step, message, **kwargs),
        agent_run_id=self.agent_run_id,
        graph_thread_id=self.graph_thread_id or (f"{self.project_id}:{self.agent_run_id}" if self.project_id and self.agent_run_id else None),
        resume_graph=self.resume_graph,
        chat_session_id=self.chat_session_id,
        project_name=self.project_name,
        patch_action=self.patch_action,
      )
      if runtime_result.get("awaiting_patch_approval"):
        generated_website = runtime_result["generated_website"]
        pending = runtime_result.get("patch_approval") if isinstance(runtime_result.get("patch_approval"), dict) else {}
        state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
        state.response = build_website_generation_response(
          state,
          generated_website=generated_website,
          artifact_response=state.raw_llm_response,
        )
        state.response["multi_agent_system"]["conversation_response"] = patch_approval_conversation_response(pending)
        state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
        apply_backend_routing_to_response(state)
        self._emit_progress(
          "patch.approval.required",
          "Paused before commit — waiting for patch approval",
          status="running",
          detail={"patch_approval": pending},
        )
        trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="awaiting_patch_approval")
        return state.response["orchestration_flow"]
      generated_website = runtime_result["generated_website"]
      state.raw_llm_response = enrich_artifact_response_from_runtime(runtime_result)
      state.response = build_website_generation_response(
        state,
        generated_website=generated_website,
        artifact_response=state.raw_llm_response,
      )
      state.response["multi_agent_system"]["agentic_runtime"] = runtime_result["runtime"]
      state.response["gemini_tool_calling_setup"]["runtime_trace"] = {
        "runtime_status": "completed",
        "provider": "gemini-native-control-artifact",
        "model": provider_name(state.artifact_client),
        "tool_calls": runtime_result["runtime"].get("tool_calls", []),
        "final_response_text": state.response["multi_agent_system"]["conversation_response"]["message"],
      }
      state.response["gemini_tool_calling_setup"]["tool_call_sequence"] = [
        "route_generation_action",
        "READ_PROJECT_FILES",
        "LOAD_PROJECT_MEMORY",
        "analyze_update_request" if state.intent == "website_update" else "analyze_prompt",
        "VALIDATE_PROJECT_ARTIFACT",
        "BUILD_STAGED_PROJECT_PREVIEW",
        "RUN_PREVIEW_VISUAL_QA",
        "WRITE_PROJECT_FILES",
      ]
      state.response["gemini_tool_calling_setup"]["tools"] = merge_tool_registry_entries(
        state.response["gemini_tool_calling_setup"].get("tools", []),
        real_backend_tool_registry_entries(),
      )
      state.response["proactive_thinking"]["self_checks"] = [
        *state.response["proactive_thinking"].get("self_checks", []),
        "Files were written through WRITE_PROJECT_FILES",
        "Preview was built from staged files through BUILD_STAGED_PROJECT_PREVIEW",
      ]
      apply_backend_routing_to_response(state)
      log_generated_website_tools(state.response)
      self._emit_progress("agent.runtime.loop.completed", "Real agent/tool runtime loop completed", status="completed")
      trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="real_agent_runtime")
      return state.response["orchestration_flow"]

    if not self.allow_legacy_fallback:
      raise ResponseContractError("Website generation requires project_id, tool_context, and user for the real agent runtime.")

    self._emit_progress("legacy_generation.enabled", "Using explicit legacy one-shot generation fallback")
    state.prepared_sections["domain_research"] = build_domain_research_context(state.user_prompt)
    prompt = build_website_prompt(
      state.user_prompt,
      adk_mapping=format_adk_mapping_for_prompt(),
      pipeline_context=json.dumps(state.prepared_sections, indent=2),
      artifact_mode="website_update" if state.intent == "website_update" else "website_generation",
    )
    client = state.artifact_client or GeminiProvider()
    self._emit_progress("generate_website_artifact.input", "Sending website artifact request to Gemini/code provider")
    state.raw_llm_response = client.generate_json(
      prompt,
      trace_label="update_website_artifact" if state.intent == "website_update" else "generate_website_artifact",
    )
    self._emit_progress("generate_website_artifact.output", "Gemini returned a website artifact", status="completed")
    self._emit_progress("artifact.validation", "Validating generated sections, theme, and files")
    generated_website = normalize_generated_website_artifact(state.raw_llm_response)
    self._emit_progress(
      "artifact.validated",
      f"Validated {len(generated_website.get('files') or [])} files and {len(generated_website.get('sections') or [])} sections",
      status="completed",
      detail={
        "file_count": len(generated_website.get("files") or []),
        "section_count": len(generated_website.get("sections") or []),
      },
    )
    state.response = build_website_generation_response(
      state,
      generated_website=generated_website,
      artifact_response=state.raw_llm_response,
    )
    apply_backend_routing_to_response(state)
    log_generated_website_tools(state.response)
    trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="legacy_generation")
    return state.response["orchestration_flow"]

  def agent_to_agent_communication(self, state: GenerationPipelineState) -> dict[str, Any]:
    response = require_pipeline_response(state)
    communication = response["agent_to_agent_communication"]
    communication["backend_stage_order"] = list(PIPELINE_STAGE_ORDER)
    state.prepared_sections["agent_to_agent_communication"] = communication
    return communication

  def proactive_thinking(self, state: GenerationPipelineState) -> dict[str, Any]:
    response = require_pipeline_response(state)

    proactive = response["proactive_thinking"]
    proactive["backend_execution"] = {
      "pipeline_stage_order": list(PIPELINE_STAGE_ORDER),
      "completed_stages": [entry for entry in state.stage_trace if entry["status"] == "completed"],
    }
    return proactive
