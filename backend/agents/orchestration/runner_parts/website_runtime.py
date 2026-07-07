from __future__ import annotations

from typing import Any

from backend.debug_trace import trace_print

from backend.agents.agent_runtime.errors import AgentRuntimeLoopError
from backend.agents.agent_runtime_loop import execute_real_agent_runtime_loop
from backend.agents.followup_routing import apply_existing_project_routing_bias
from backend.agents.generation_engine.greenfield_runner import run_website_generation
from backend.agents.orchestration.provider_utils import default_control_provider
from backend.agents.providers import GeminiProvider
from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_FEATURE_UPDATE,
  ADAPTIVE_ROUTE_FULL_GENERATION,
  ADAPTIVE_ROUTE_LARGE_PROJECT,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
)
from backend.agents.runtime_config import (
  langgraph_website_runtime_enabled,
  parallel_stream_orchestrator_enabled,
  parallel_website_generation_default,
  should_use_parallel_website_workflow,
  streaming_fast_path_enabled,
  streaming_file_agent_enabled,
  unified_website_updates_active,
)
from backend.agents.schema import ResponseContractError
from backend.agents.streaming.file_agent import is_error_repair_prompt, run_streaming_file_agent
from backend.agents.streaming.parallel_orchestrator import run_parallel_stream_orchestrator
from backend.visual_qa import ensure_update_visual_baseline
from .runtime_result import finalize_runtime_generated_website


def _failed_update_runtime_result(*, title: str, prompt: str, workflow: str, error: Exception) -> dict[str, Any]:
  message = str(error).strip() or "The update agent failed before producing a file patch."
  return {
    "artifact_response": {
      "no_code_changes": True,
      "summary": message,
      "generated_website": {
        "title": title or "Website update",
        "headline": "Website update not applied",
        "subheadline": message,
        "primary_cta": "Retry update",
        "secondary_cta": "Review runtime details",
        "preview_html": "",
        "theme": {
          "colors": {
            "primary": "#2563eb",
            "secondary": "#0f172a",
            "accent": "#f97316",
            "background": "#ffffff",
            "text": "#111827",
          }
        },
        "sections": [
          {
            "name": "Runtime failure",
            "purpose": "Explain why the existing project was preserved.",
            "content": message,
            "items": [prompt],
          }
        ],
        "files": [],
      },
    },
    "generated_website": {
      "title": title or "Website update",
      "headline": "Website update not applied",
      "subheadline": message,
      "primary_cta": "Retry update",
      "secondary_cta": "Review runtime details",
      "preview_html": "",
      "theme": {
        "colors": {
          "primary": "#2563eb",
          "secondary": "#0f172a",
          "accent": "#f97316",
          "background": "#ffffff",
          "text": "#111827",
        }
      },
      "sections": [
        {
          "name": "Runtime failure",
          "purpose": "Explain why the existing project was preserved.",
          "content": message,
          "items": [prompt],
        }
      ],
      "files": [],
    },
    "runtime": {
      "runtime": workflow,
      "workflow": workflow,
      "status": "failed",
      "branch": "website_update",
      "operation": "website_update",
      "source": "failed_update_runtime",
      "no_code_changes": True,
      "tool_source_of_truth": False,
      "output_text": message,
      "changed_paths": [],
    },
    "local_sync": None,
    "preview": None,
  }


def handle_website_runtime_branch(orchestrator: Any, state: Any) -> dict[str, Any]:
  website_intents = {"website_generation", "website_update"}
  store = getattr(orchestrator.tool_context, "store", None) if orchestrator.tool_context is not None else None
  chat_topic_id = getattr(orchestrator, "chat_topic_id", None)
  runtime_ready = orchestrator.project_id and orchestrator.tool_context is not None and orchestrator.user is not None and hasattr(store, "list_files")
  adaptive_route = state.adaptive_route or {}
  adaptive_route_name = str(adaptive_route.get("route") or "").strip()
  prefer_streaming_error_repair = state.intent == "website_update" and is_error_repair_prompt(state.user_prompt)
  large_update_route = adaptive_route_name in {ADAPTIVE_ROUTE_LARGE_PROJECT, ADAPTIVE_ROUTE_FULL_GENERATION}
  unified_update_prefers_scoped_streaming = (
    unified_website_updates_active()
    and state.intent == "website_update"
    and runtime_ready
    and streaming_file_agent_enabled()
    and not large_update_route
  )
  use_parallel_stream_for_website = (
    runtime_ready
    and state.intent in website_intents
    and streaming_file_agent_enabled()
    and parallel_stream_orchestrator_enabled()
    and parallel_website_generation_default()
    and large_update_route
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
      or unified_update_prefers_scoped_streaming
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
      ensure_update_visual_baseline(
        project_id=orchestrator.project_id,
        user=orchestrator.user,
        tool_context=orchestrator.tool_context,
        prompt=state.user_prompt,
        chat_session_id=orchestrator.chat_session_id,
        agent_run_id=orchestrator.agent_run_id,
        emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
      )
    except Exception as exc:
      orchestrator._emit_progress("automation.baseline.failed", f"Before-update screenshot baseline check failed: {exc}", status="failed", detail={"error": str(exc)})

  if state.intent == "website_generation" and runtime_ready and streaming_file_agent_enabled():
    orchestrator._emit_progress("agent.decision", "Using greenfield generation engine for new website build", status="completed", detail={"intent": state.intent, "selected_agent": "Greenfield Generation Engine", "workflow": "greenfield_generation"})
    runtime_result = run_website_generation(
      project_id=orchestrator.project_id,
      user=orchestrator.user,
      tool_context=orchestrator.tool_context,
      prompt=state.user_prompt,
      artifact_provider=state.artifact_client or GeminiProvider(),
      emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
      attachments=state.attachments,
      chat_session_id=orchestrator.chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=orchestrator.project_name,
      patch_action=orchestrator.patch_action,
      agent_run_id=orchestrator.agent_run_id,
      confirmation_brief=state.confirmation_brief,
    )
    workflow_label = str((runtime_result.get("runtime") or {}).get("workflow") or "greenfield_generation")
    return finalize_runtime_generated_website(
      orchestrator,
      state,
      runtime_result,
      workflow_label=workflow_label,
      runtime_provider=workflow_label,
      tool_call_sequence=["plan_greenfield_tasks", "greenfield_generation", "read_file", "list_files", "write_file", "str_replace", "WRITE_PROJECT_FILES"],
      extra_self_checks=[f"Files were written through the {workflow_label}"],
      merge_backend_tools=True,
    )

  if use_parallel_stream_for_website:
    orchestrator._emit_progress("orchestrator.starting", "Planning parallel file workers and starting multi-agent generation", status="running", detail={"intent": state.intent, "workflow": "parallel_stream_orchestrator"})
    runtime_result = run_parallel_stream_orchestrator(
      project_id=orchestrator.project_id,
      user=orchestrator.user,
      tool_context=orchestrator.tool_context,
      prompt=state.user_prompt,
      intent=state.intent,
      artifact_provider=state.artifact_client or GeminiProvider(),
      emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
      attachments=state.attachments,
      chat_session_id=orchestrator.chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=orchestrator.project_name,
      patch_action=orchestrator.patch_action,
    )
    return finalize_runtime_generated_website(
      orchestrator,
      state,
      runtime_result,
      workflow_label="parallel_stream_orchestrator",
      runtime_provider="parallel_stream_orchestrator",
      tool_call_sequence=["plan_file_work", "parallel_file_workers", "agent.parallel.wave", "read_file", "list_files", "write_file", "str_replace", "WRITE_PROJECT_FILES"],
      extra_self_checks=["Files were written through the parallel_stream_orchestrator"],
      merge_backend_tools=True,
    )

  if use_langgraph_for_website:
    orchestrator._emit_progress("agent.runtime.loop.started", "Starting LangGraph agent runtime (default path)", status="running", detail={"intent": state.intent, "workflow": "langgraph_runtime_default"})
    execute_real_agent_runtime_loop_fn = execute_real_agent_runtime_loop
    try:
      runtime_result = execute_real_agent_runtime_loop_fn(
        project_id=orchestrator.project_id,
        user=orchestrator.user,
        tool_context=orchestrator.tool_context,
        prompt=state.user_prompt,
        routing_result=state.routing_result,
        control_provider=state.control_client or default_control_provider(),
        artifact_provider=state.artifact_client or GeminiProvider(),
        prepared_sections=state.prepared_sections,
        emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
        agent_run_id=orchestrator.agent_run_id,
        graph_thread_id=orchestrator.graph_thread_id or (f"{orchestrator.project_id}:{orchestrator.agent_run_id}" if orchestrator.project_id and orchestrator.agent_run_id else None),
        resume_graph=orchestrator.resume_graph,
        chat_session_id=orchestrator.chat_session_id,
        chat_topic_id=chat_topic_id,
        project_name=orchestrator.project_name,
        patch_action=orchestrator.patch_action,
      )
    except AgentRuntimeLoopError as exc:
      if state.intent != "website_update":
        raise
      runtime_result = _failed_update_runtime_result(
        title=orchestrator.project_name,
        prompt=state.user_prompt,
        workflow="langgraph_runtime_default",
        error=exc,
      )
    return finalize_runtime_generated_website(
      orchestrator,
      state,
      runtime_result,
      workflow_label="langgraph_runtime_default",
      runtime_provider="langgraph_runtime_default",
      trace_branch="langgraph_runtime_default",
    )

  if use_streaming_single_agent:
    orchestrator._emit_progress("agent.decision", "Using fast streaming file agent for this request", status="completed", detail={"intent": state.intent, "selected_agent": "Streaming File Agent", "selected_action": "streaming_file_agent", "decision_source": "streaming_file_agent_fast_path", "workflow": "streaming_file_agent"})
    runtime_result = run_streaming_file_agent(
      project_id=orchestrator.project_id,
      user=orchestrator.user,
      tool_context=orchestrator.tool_context,
      prompt=state.user_prompt,
      intent=state.intent,
      artifact_provider=state.artifact_client or GeminiProvider(),
      emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
      attachments=state.attachments,
      chat_session_id=orchestrator.chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=orchestrator.project_name,
      patch_action=orchestrator.patch_action,
      agent_run_id=orchestrator.agent_run_id,
      target_resolution=state.routing_result.get("target_resolution") if isinstance(state.routing_result, dict) else None,
    )
    return finalize_runtime_generated_website(
      orchestrator,
      state,
      runtime_result,
      workflow_label="streaming_file_agent",
      runtime_provider="streaming_file_agent",
      tool_call_sequence=["plan_file_work", "parallel_file_workers", "agent.parallel.wave", "read_file", "list_files", "write_file", "str_replace", "WRITE_PROJECT_FILES"],
      extra_self_checks=["Files were written through the streaming_file_agent"],
      merge_backend_tools=True,
    )

  if orchestrator.project_id and orchestrator.tool_context is not None and orchestrator.user is not None:
    orchestrator._emit_progress("agent.runtime.loop.started", "Starting real agent/tool runtime loop")
    try:
      runtime_result = execute_real_agent_runtime_loop(
        project_id=orchestrator.project_id,
        user=orchestrator.user,
        tool_context=orchestrator.tool_context,
        prompt=state.user_prompt,
        routing_result=state.routing_result,
        control_provider=state.control_client or default_control_provider(),
        artifact_provider=state.artifact_client or GeminiProvider(),
        prepared_sections=state.prepared_sections,
        emit_progress=lambda step, message, **kwargs: orchestrator._emit_progress(step, message, **kwargs),
        agent_run_id=orchestrator.agent_run_id,
        graph_thread_id=orchestrator.graph_thread_id or (f"{orchestrator.project_id}:{orchestrator.agent_run_id}" if orchestrator.project_id and orchestrator.agent_run_id else None),
        resume_graph=orchestrator.resume_graph,
        chat_session_id=orchestrator.chat_session_id,
        chat_topic_id=chat_topic_id,
        project_name=orchestrator.project_name,
        patch_action=orchestrator.patch_action,
      )
    except AgentRuntimeLoopError as exc:
      if state.intent != "website_update":
        raise
      runtime_result = _failed_update_runtime_result(
        title=orchestrator.project_name,
        prompt=state.user_prompt,
        workflow="gemini-native-control-artifact",
        error=exc,
      )
    return finalize_runtime_generated_website(
      orchestrator,
      state,
      runtime_result,
      workflow_label="gemini-native-control-artifact",
      runtime_provider="gemini-native-control-artifact",
      trace_branch="real_agent_runtime",
      tool_call_sequence=["route_generation_action", "READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "analyze_update_request" if state.intent == "website_update" else "analyze_prompt", "VALIDATE_PROJECT_ARTIFACT", "BUILD_STAGED_PROJECT_PREVIEW", "RUN_PREVIEW_VISUAL_QA", "WRITE_PROJECT_FILES"],
      extra_self_checks=["Files were written through WRITE_PROJECT_FILES", "Preview was built from staged files through BUILD_STAGED_PROJECT_PREVIEW"],
      merge_backend_tools=True,
      completion_progress=("agent.runtime.loop.completed", "Real agent/tool runtime loop completed", "completed"),
    )

  return None
