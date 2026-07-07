from __future__ import annotations

import time
from typing import Any, Callable

from backend.debug_trace import trace_function, trace_print
from ...orchestration_graph import execute_orchestration_stage_graph
from backend.agents.runtime_config import (
  runtime_engine,
  streaming_file_agent_enabled,
)
from backend.agents.providers import (
  LLMProvider,
)
from backend.agents.requirement_confirmation import (
  load_pending_confirmation,
  load_retryable_confirmation,
  looks_like_confirmation_reply,
)
from backend.agents.schema import ResponseContractError, sanitize_generation_response
from ..artifact_response import (
  build_website_generation_response,
  enrich_artifact_response_from_runtime,
  log_generated_website_tools,
)
from ..provider_utils import provider_name
from .runtime_result import finalize_runtime_generated_website
from ..live_runtime_trace import attach_live_runtime_metadata
from ..runtime_metadata import existing_agentic_runtime
from ..state import GenerationPipelineState
from .core_parts import agent_to_agent_communication as core_agent_to_agent_communication
from .core_parts import emit_progress
from .core_parts import execute_stage
from .core_parts import gemini_tool_calling_setup as core_gemini_tool_calling_setup
from .core_parts import google_adk_usage as core_google_adk_usage
from .core_parts import multi_agent_system as core_multi_agent_system
from .core_parts import orchestration_flow as core_orchestration_flow
from .core_parts import proactive_thinking as core_proactive_thinking
from .core_parts.routing import build_routing_context
from .core_parts import resolve_artifact_provider
from .core_parts import resolve_control_provider


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
    chat_topic_id: str | None = None,
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
    self.chat_topic_id = chat_topic_id
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

    control_client = self._resolve_control_provider()
    artifact_client = self._resolve_artifact_provider()
    trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="resolve_providers", control=provider_name(control_client), artifact=provider_name(artifact_client))
    routing_context = build_routing_context(
      self,
      user_prompt,
      confirmation_action=confirmation_action,
      control_client=control_client,
      artifact_client=artifact_client,
    )
    execution_prompt = routing_context["execution_prompt"]
    routing_result = routing_context["routing_result"]
    conversation_response_override = routing_context["conversation_response_override"]
    confirmation_brief = routing_context["confirmation_brief"]
    adaptive_route = routing_context["adaptive_route"]
    pending_confirmation = routing_context["pending_confirmation"]

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
      from ...graph_runtime.orchestration_graph import execute_langgraph_orchestration

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
    if use_langgraph_orchestration:
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
    return resolve_control_provider(self)

  def _resolve_artifact_provider(self) -> Any:
    return resolve_artifact_provider(self)

  def _emit_progress(
    self,
    step: str,
    message: str,
    *,
    status: str = "running",
    detail: dict[str, Any] | None = None,
    audit_detail: dict[str, Any] | None = None,
  ) -> None:
    emit_progress(self, step, message, status=status, detail=detail, audit_detail=audit_detail)

  def _execute_stage(
    self,
    stage_name: str,
    handler: Callable[[GenerationPipelineState], dict[str, Any]],
    state: GenerationPipelineState,
  ) -> None:
    execute_stage(self, stage_name, handler, state)

  def multi_agent_system(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_multi_agent_system(self, state)

  def gemini_tool_calling_setup(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_gemini_tool_calling_setup(self, state)

  def google_adk_usage(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_google_adk_usage(self, state)

  def orchestration_flow(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_orchestration_flow(self, state)

  def agent_to_agent_communication(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_agent_to_agent_communication(self, state)

  def proactive_thinking(self, state: GenerationPipelineState) -> dict[str, Any]:
    return core_proactive_thinking(self, state)
