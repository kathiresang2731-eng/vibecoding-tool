from __future__ import annotations

import os
from time import monotonic
from typing import Any, Callable

from fastapi import HTTPException

try:
  from ..agent_runtime import build_agent_run_input, persist_agent_runtime_output
  from ..agent_tools import ToolRuntimeContext
  from ..audit_logging import current_telemetry_context, log_query_event, telemetry_scope, update_telemetry_context, RunTelemetryContext
  from ..code_diff import build_project_diff, redact_project_diff_for_audit
  from ..debug_trace import trace_function, trace_print
  from ..agents.memory.context import build_agent_flow_memory_block
  from ..agents.memory.session_monitor import persist_generation_memory_checkpoint
  from ..agents.project_workspace import is_greenfield_codebase, meaningful_project_source_files
  from ..agents.chat_history import (
    MAX_STORED_HISTORY_MESSAGES,
    apply_chat_context_budget,
    build_current_project_context_contents,
    build_gemini_chat_history_contents,
    build_model_chat_memory_text,
    build_project_path_index_contents,
    enrich_website_modification_prompt,
    latest_enhancement_context,
    latest_error_context,
  )
  from ..agents.runtime_config import streaming_file_agent_enabled
  from ..agents.request_complexity import (
    ADAPTIVE_ROUTE_FEATURE_UPDATE,
    ADAPTIVE_ROUTE_FULL_GENERATION,
    ADAPTIVE_ROUTE_LARGE_PROJECT,
    ADAPTIVE_ROUTE_SMALL_CODE,
    ADAPTIVE_ROUTE_TARGETED_UPDATE,
    ADAPTIVE_ROUTE_TINY_CHAT,
    classify_adaptive_request_route,
  )
  from ..agents.generator import generate_website
  from ..agents.requirement_confirmation import looks_like_confirmation_reply
  from ..agentic.tools.handlers import pull_linked_workspace_to_store
  from ..agents.orchestration.conversation import build_conversation_generation_response, deterministic_conversation_response
  from ..agents.orchestration.state import GenerationPipelineState
  from ..agents.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, DUAL_PROVIDER_ROLE, GeminiProvider
  from ..local_workspace import LocalWorkspaceError
  from ..runtime_control import runtime_cancellation_scope
  from ..storage import StorageError, UserContext
  from .run_locks import acquire_project_run_lock, raise_if_project_run_cancelled
except ImportError:
  from agent_runtime import build_agent_run_input, persist_agent_runtime_output
  from agent_tools import ToolRuntimeContext
  from audit_logging import current_telemetry_context, log_query_event, telemetry_scope, update_telemetry_context, RunTelemetryContext
  from code_diff import build_project_diff, redact_project_diff_for_audit
  from debug_trace import trace_function, trace_print
  from agents.chat_history import (
    MAX_STORED_HISTORY_MESSAGES,
    apply_chat_context_budget,
    build_current_project_context_contents,
    build_gemini_chat_history_contents,
    build_model_chat_memory_text,
    build_project_path_index_contents,
    enrich_website_modification_prompt,
    latest_enhancement_context,
    latest_error_context,
  )
  from agents.runtime_config import streaming_file_agent_enabled
  from agents.request_complexity import (
    ADAPTIVE_ROUTE_FEATURE_UPDATE,
    ADAPTIVE_ROUTE_FULL_GENERATION,
    ADAPTIVE_ROUTE_LARGE_PROJECT,
    ADAPTIVE_ROUTE_SMALL_CODE,
    ADAPTIVE_ROUTE_TARGETED_UPDATE,
    ADAPTIVE_ROUTE_TINY_CHAT,
    classify_adaptive_request_route,
  )
  from agents.memory.context import build_agent_flow_memory_block
  from agents.memory.session_monitor import persist_generation_memory_checkpoint
  from agents.project_workspace import is_greenfield_codebase, meaningful_project_source_files
  from agents.generator import generate_website
  from agents.requirement_confirmation import looks_like_confirmation_reply
  from agentic.tools.handlers import pull_linked_workspace_to_store
  from agents.orchestration.conversation import build_conversation_generation_response, deterministic_conversation_response
  from agents.orchestration.state import GenerationPipelineState
  from agents.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, DUAL_PROVIDER_ROLE, GeminiProvider
  from local_workspace import LocalWorkspaceError
  from runtime_control import runtime_cancellation_scope
  from storage import StorageError, UserContext
  from api.run_locks import acquire_project_run_lock, raise_if_project_run_cancelled

from .context import AppContext
from .failures import generation_failure_payload, normalize_generation_model
from .local_workspaces import write_linked_project_files
from .progress import emit_progress

try:
  from ..skills.injector import build_skill_recommendation_block, build_skills_prompt_block
  from ..skills.matcher import user_opted_into_skills
  from ..skills.runtime import resolve_skill_request
  from ..skills.agents_md import build_project_agents_md_block
except ImportError:
  from skills.injector import build_skill_recommendation_block, build_skills_prompt_block
  from skills.matcher import user_opted_into_skills
  from skills.runtime import resolve_skill_request
  from skills.agents_md import build_project_agents_md_block


_SIMPLE_GREETING_VALUES = {
  "hi",
  "hii",
  "hiii",
  "hello",
  "hey",
  "hey there",
  "hello there",
  "good morning",
  "good afternoon",
  "good evening",
}

_DEFAULT_CREDIT_RESERVATION_BY_ROUTE = {
  ADAPTIVE_ROUTE_TINY_CHAT: 0.0,
  ADAPTIVE_ROUTE_SMALL_CODE: 2.0,
  ADAPTIVE_ROUTE_TARGETED_UPDATE: 8.0,
  ADAPTIVE_ROUTE_FEATURE_UPDATE: 20.0,
  ADAPTIVE_ROUTE_LARGE_PROJECT: 60.0,
  ADAPTIVE_ROUTE_FULL_GENERATION: 80.0,
}


def default_credit_reservation_for_route(route: str | None) -> float:
  return float(_DEFAULT_CREDIT_RESERVATION_BY_ROUTE.get(str(route or "").strip(), 10.0))


def resolve_credit_reservation_estimate(route: str | None, explicit_estimate: float | int | None) -> float:
  if explicit_estimate is None:
    return default_credit_reservation_for_route(route)
  try:
    return max(0.0, float(explicit_estimate))
  except (TypeError, ValueError):
    return default_credit_reservation_for_route(route)


def _compatibility_export(name: str, fallback: Any) -> Any:
  try:
    from .. import main as main_facade

    return getattr(main_facade, name, fallback)
  except Exception:
    return fallback


def _list_project_chat_messages_compat(store: Any, project_id: str, user: UserContext, *, limit: int, chat_session_id: str | None) -> list[dict[str, Any]]:
  if not hasattr(store, "list_project_chat_messages"):
    return []
  try:
    return store.list_project_chat_messages(project_id, user, limit=limit, chat_session_id=chat_session_id)
  except TypeError as exc:
    if "chat_session_id" not in str(exc):
      raise
    return store.list_project_chat_messages(project_id, user, limit=limit)


def _record_project_chat_message_compat(
  store: Any,
  project_id: str,
  user: UserContext,
  *,
  role: str,
  content: str,
  metadata: dict[str, Any] | None = None,
  chat_session_id: str | None = None,
) -> Any:
  if not hasattr(store, "record_project_chat_message"):
    return None
  try:
    return store.record_project_chat_message(
      project_id,
      user,
      role=role,
      content=content,
      metadata=metadata,
      chat_session_id=chat_session_id,
    )
  except TypeError as exc:
    if "chat_session_id" not in str(exc):
      raise
    return store.record_project_chat_message(project_id, user, role=role, content=content, metadata=metadata)


def is_simple_greeting_prompt(prompt: str) -> bool:
  normalized = " ".join(str(prompt or "").strip().lower().replace("!", " ").replace(".", " ").split())
  return normalized in _SIMPLE_GREETING_VALUES


def build_greeting_fast_path_routing_result(*, llm_authored: bool) -> dict[str, Any]:
  return {
    "intent": "greeting",
    "next_action": "respond_and_collect_website_brief",
    "next_tool": "handle_greeting",
    "confidence": 1.0,
    "reason": (
      "Simple greeting was handled by the LLM greeting fast path."
      if llm_authored
      else "Simple greeting was handled by the deterministic greeting fallback."
    ),
  }


def greeting_fast_path_adk_usage(*, llm_authored: bool) -> dict[str, Any]:
  return {
    "enabled": False,
    "runtime": "llm-greeting-fast-path" if llm_authored else "deterministic-greeting-fallback",
    "adk_agents": [
      {
        "adk_type": "LlmAgent",
        "name": "greeting_handler_agent",
        "purpose": "Responds immediately to simple greetings and asks for the website brief.",
      },
      {
        "adk_type": "AgentTool",
        "name": "handle_greeting_tool",
        "purpose": "Fast path for greeting-only turns without artifact generation.",
      },
    ],
    "notes": [
      (
        "Simple greeting handled by the selected model without full routing or artifact generation."
        if llm_authored
        else "Simple greeting handled by fallback without full routing or artifact generation."
      )
    ],
  }


def normalize_greeting_lines(message: str) -> str:
  lines = [line.strip() for line in str(message or "").splitlines() if line.strip()]
  if not lines:
    return "Hi there — tell me what website or app you'd like to create."
  return "\n".join(lines[:3])


def build_fast_greeting_generation(prompt: str, model_provider: Any | None = None) -> dict[str, Any]:
  try:
    from ..agents.orchestration.conversation import (
      build_conversation_generation_response,
      deterministic_conversation_response,
      generate_conversation_response,
    )
    from ..agents.orchestration.state import GenerationPipelineState
  except ImportError:
    from agents.orchestration.conversation import (
      build_conversation_generation_response,
      deterministic_conversation_response,
      generate_conversation_response,
    )
    from agents.orchestration.state import GenerationPipelineState

  llm_authored = model_provider is not None
  routing_result = {
    **build_greeting_fast_path_routing_result(llm_authored=llm_authored),
  }
  state = GenerationPipelineState(
    user_prompt=prompt,
    intent="greeting",
    routing_result=routing_result,
    prepared_sections={
      "google_adk_usage": greeting_fast_path_adk_usage(llm_authored=llm_authored)
    },
  )
  if model_provider is not None:
    try:
      conversation = generate_conversation_response(state, model_provider)
      conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
    except Exception:
      conversation = deterministic_conversation_response(state, error="greeting orchestration fallback")
      conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
  else:
    conversation = deterministic_conversation_response(state, error="deterministic greeting fallback")
    conversation["message"] = normalize_greeting_lines(conversation.get("message") or "")
  return build_conversation_generation_response(state, conversation)


def _project_workspace_root(project: dict[str, Any]) -> Any:
  from pathlib import Path

  local_path = str(project.get("local_path") or "").strip()
  if not local_path:
    return None
  root = Path(local_path).expanduser()
  return root if root.is_dir() else None


def _persist_memory_checkpoint_safe(
  store: Any,
  user: UserContext,
  *,
  project_id: str,
  chat_session_id: str | None,
  generation_run_id: str | None,
  prompt: str,
  intent: str,
  outcome: str,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
  error_category: str | None = None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  try:
    return persist_generation_memory_checkpoint(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
      prompt=prompt,
      intent=intent,
      outcome=outcome,
      project_name=project_name,
      files=files,
      changed_paths=changed_paths,
      preview_status=preview_status,
      error_category=error_category,
      extra=extra,
    )
  except Exception:
    return {"status": "skipped", "reason": "persist_failed"}


def append_orchestrator_context(
  prompt: str,
  *,
  error_context: str | None,
  enhancement_context: str | None,
  skills_block: str | None = None,
  episodic_context: str | None = None,
  agents_md_block: str | None = None,
) -> str:
  context_blocks: list[str] = []
  if agents_md_block:
    context_blocks.append(agents_md_block.strip())
  if skills_block:
    context_blocks.append(skills_block.strip())
  if episodic_context:
    context_blocks.append(episodic_context.strip())
  if error_context:
    context_blocks.append(
      "Previous runtime/build error context available to the Chief Orchestrator:\n"
      f"{error_context}\n\n"
      "If this error context mentions local environment, local helper, terminal action, "
      "dependency installation, folder access, or workspace access, route the turn through "
      "the Universal Error Handling Agent with terminal handling instructions. Prefer using "
      "the user's local Worktual helper actions for git status, dependency install guidance, "
      "tests, and build validation before proposing code changes. Do not assume the server "
      "terminal can access another user's home directory."
    )
  if enhancement_context:
    context_blocks.append(
      "Previous enhancement-plan context available to the Chief Orchestrator:\n"
      f"{enhancement_context}"
    )
  if not context_blocks:
    return prompt
  return (
    f"{prompt}\n\n"
    "Additional conversation context for model routing and planning. "
    "Use it only if the current user request refers to or depends on it; otherwise ignore it.\n\n"
    + "\n\n".join(context_blocks)
  )


def generation_model_chat_metadata(
  generation: dict[str, Any],
  *,
  base_metadata: dict[str, Any] | None = None,
  local_sync: Any = None,
  local_sync_error: str | None = None,
) -> tuple[str, dict[str, Any]]:
  memory_content = build_model_chat_memory_text(
    generation,
    local_sync=local_sync,
    local_sync_error=local_sync_error,
  )
  metadata = dict(base_metadata or {})
  multi_agent = generation.get("multi_agent_system") if isinstance(generation, dict) else {}
  conversation = multi_agent.get("conversation_response") if isinstance(multi_agent, dict) else {}
  if isinstance(conversation, dict):
    display_content = str(conversation.get("message") or "").strip()
    if display_content:
      metadata["display_content"] = display_content
    confirmation = conversation.get("confirmation")
    if isinstance(confirmation, dict) and confirmation:
      metadata["confirmation"] = confirmation
  return memory_content, metadata


def should_sync_linked_local_folder(project: dict[str, Any], local_sync: Any) -> bool:
  if not project.get("local_path"):
    return False
  if not isinstance(local_sync, dict):
    return True
  return local_sync.get("direction") != "push" or not local_sync.get("path")


def original_files_for_generated_paths(
  original_files: list[dict[str, Any]],
  generated_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  generated_paths = {
    str(file_item.get("path") or "").strip()
    for file_item in generated_files
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip()
  }
  if not generated_paths:
    return []
  return [
    file_item
    for file_item in original_files
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip() in generated_paths
  ]


def is_hidden_project_file_path(path: str) -> bool:
  return any(segment.startswith(".") for segment in str(path or "").replace("\\", "/").split("/") if segment)


def visible_project_files(files: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
  return [
    item
    for item in files or []
    if isinstance(item, dict) and not is_hidden_project_file_path(str(item.get("path") or ""))
  ]


def resolve_control_model_for_request(selected_model: str | None) -> str | None:
  configured = str(os.getenv("GEMINI_CONTROL_MODEL") or "").strip()
  if configured:
    return configured
  default_control = str(os.getenv("GEMINI_DEFAULT_CONTROL_MODEL") or "gemini-3.5-flash").strip()
  if selected_model == "gemini-3.1-pro-preview":
    return default_control
  return selected_model or default_control


def build_gemini_provider(
  provider_cls: Any,
  *,
  model: str | None,
  provider_role: str,
  existing_provider: Any | None = None,
) -> Any:
  if existing_provider is not None and getattr(existing_provider, "provider_role", None) == DUAL_PROVIDER_ROLE:
    return existing_provider
  try:
    return provider_cls(model=model, provider_role=provider_role)
  except TypeError:
    return provider_cls(model=model)


@trace_function(project_id=lambda project_id, *_args, **_kwargs: project_id, model=lambda *_args, model=None, **_kwargs: model or "default")
def run_generation_pipeline(
  project_id: str,
  prompt: str,
  context: AppContext,
  user: UserContext,
  *,
  model: str | None = None,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  system_name: str | None = None,
  chat_session_id: str | None = None,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  patch_action: str | None = None,
  model_policy: str = "auto_staged",
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
  _telemetry_initialized: bool = False,
) -> dict[str, Any]:
  if confirmation_action not in {"confirm", "cancel"}:
    confirmation_action = None
  if patch_action not in {"approve", "reject"}:
    patch_action = None
  if not _telemetry_initialized:
    telemetry = RunTelemetryContext.create(user_id=user.id, project_id=project_id)
    with telemetry_scope(telemetry):
      return run_generation_pipeline(
        project_id,
        prompt,
        context,
        user,
        model=model,
        progress_callback=progress_callback,
        system_name=system_name,
        chat_session_id=chat_session_id,
        confirmation_action=confirmation_action,
        attachments=attachments,
        patch_action=patch_action,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
        _telemetry_initialized=True,
      )

  with acquire_project_run_lock(project_id, user_id=getattr(user, "id", "")) as active_run:
    with runtime_cancellation_scope(lambda: raise_if_project_run_cancelled(active_run)):
      return _run_generation_pipeline_unlocked(
        project_id,
        prompt,
        context,
        user,
        model=model,
        progress_callback=progress_callback,
        system_name=system_name,
        chat_session_id=chat_session_id,
        confirmation_action=confirmation_action,
        active_run=active_run,
        attachments=attachments,
        patch_action=patch_action,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
      )


def run_generation_resume(
  project_id: str,
  prompt: str,
  context: AppContext,
  user: UserContext,
  *,
  thread_id: str | None = None,
  model: str | None = None,
  model_policy: str = "auto_staged",
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
  resume_graph: bool = False,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  chat_session_id: str | None = None,
  _telemetry_initialized: bool = False,
) -> dict[str, Any]:
  if not _telemetry_initialized:
    telemetry = RunTelemetryContext.create(user_id=user.id, project_id=project_id)
    with telemetry_scope(telemetry):
      return run_generation_resume(
        project_id,
        prompt,
        context,
        user,
        thread_id=thread_id,
        model=model,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
        resume_graph=resume_graph,
        progress_callback=progress_callback,
        chat_session_id=chat_session_id,
        _telemetry_initialized=True,
      )

  from ..agents.graph_runtime.threading import parse_runtime_thread_id

  resolved_thread_id = str(thread_id or "").strip()
  if resolved_thread_id:
    parsed_project_id, agent_run_id = parse_runtime_thread_id(resolved_thread_id)
    if parsed_project_id != project_id:
      raise ValueError("thread_id project_id does not match the requested project.")
  else:
    agent_run_id = None

  with acquire_project_run_lock(project_id, user_id=getattr(user, "id", "")) as active_run:
    with runtime_cancellation_scope(lambda: raise_if_project_run_cancelled(active_run)):
      return _run_generation_pipeline_unlocked(
        project_id,
        prompt,
        context,
        user,
        model=model,
        model_policy=model_policy,
        artifact_model=artifact_model,
        request_class=request_class,
        estimated_credit_reservation=estimated_credit_reservation,
        progress_callback=progress_callback,
        active_run=active_run,
        agent_run_id=agent_run_id,
        graph_thread_id=resolved_thread_id or None,
        resume_graph=resume_graph,
        chat_session_id=chat_session_id,
      )


def _extract_preview_status_from_generation(generation: dict[str, Any]) -> str | None:
  multi_agent = generation.get("multi_agent_system") if isinstance(generation, dict) else {}
  agentic_runtime = multi_agent.get("agentic_runtime") if isinstance(multi_agent, dict) else {}
  if not isinstance(agentic_runtime, dict):
    return None
  final_output = agentic_runtime.get("final_output")
  if isinstance(final_output, dict):
    preview_status = final_output.get("preview_status")
    if preview_status:
      return str(preview_status)
  visual_qa = agentic_runtime.get("visual_qa")
  if isinstance(visual_qa, dict):
    visual_status = visual_qa.get("status")
    if visual_status == "failed":
      return "visual_qa_failed"
  preview = agentic_runtime.get("preview")
  if isinstance(preview, dict):
    status = preview.get("status")
    if status:
      return str(status)
  build_gate = agentic_runtime.get("build_gate")
  if isinstance(build_gate, dict):
    status = build_gate.get("status")
    if status:
      return str(status)
  return None


def _run_generation_pipeline_unlocked(
  project_id: str,
  prompt: str,
  context: AppContext,
  user: UserContext,
  *,
  model: str | None = None,
  progress_callback: Callable[[dict[str, Any]], None] | None = None,
  system_name: str | None = None,
  active_run: Any | None = None,
  agent_run_id: str | None = None,
  graph_thread_id: str | None = None,
  resume_graph: bool = False,
  chat_session_id: str | None = None,
  confirmation_action: str | None = None,
  attachments: list[dict[str, Any]] | None = None,
  patch_action: str | None = None,
  model_policy: str = "auto_staged",
  artifact_model: str | None = None,
  request_class: str | None = None,
  estimated_credit_reservation: float | int | None = None,
) -> dict[str, Any]:
  if confirmation_action not in {"confirm", "cancel"}:
    confirmation_action = None
  if patch_action not in {"approve", "reject"}:
    patch_action = None
  started_at = monotonic()
  telemetry = current_telemetry_context()
  log_query_event(
    "query.received",
    status="running",
    payload={
      "prompt": prompt,
      "selected_model": model,
      "model_policy": model_policy,
      "artifact_model": artifact_model,
      "request_class": request_class,
      "estimated_credit_reservation": estimated_credit_reservation,
    },
    model=model,
  )
  emit_progress(progress_callback, "request.received", "Received prompt from workspace", status="completed")
  try:
    from .usage_enforcement import assert_user_can_generate
  except ImportError:
    from api.usage_enforcement import assert_user_can_generate
  usage_summary = assert_user_can_generate(context.store, user)
  emit_progress(
    progress_callback,
    "usage.checked",
    "Verified account AI credits before generation",
    status="completed",
    detail={"usage": usage_summary},
  )
  try:
    from ..agents.prompting.attachments import normalize_prompt_attachments
  except ImportError:
    from agents.prompting.attachments import normalize_prompt_attachments
  normalized_attachments: list[dict[str, str]] = []
  try:
    normalized_attachments = normalize_prompt_attachments(attachments or [])
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  if normalized_attachments:
    emit_progress(
      progress_callback,
      "attachments.received",
      f"Received {len(normalized_attachments)} attachment(s) with the prompt",
      status="completed",
      detail={"attachments": [{"name": item["name"], "kind": item["kind"], "mime_type": item["mime_type"]} for item in normalized_attachments]},
    )
  if not prompt.strip() and not normalized_attachments and patch_action not in {"approve", "reject"}:
    raise HTTPException(status_code=400, detail="Prompt is empty. Describe the website you want to build or attach a screenshot/file.")
  if patch_action in {"approve", "reject"}:
    try:
      from ..agents.patch_approval import resolve_patch_approval_turn
    except ImportError:
      from agents.patch_approval import resolve_patch_approval_turn
    patch_payload = resolve_patch_approval_turn(
      project_id=project_id,
      patch_action=patch_action,
      context=context,
      user=user,
      progress_callback=progress_callback,
      prompt=prompt,
    )
    resolved_chat_session_id = None
    if hasattr(context.store, "resolve_chat_session_id"):
      resolved_chat_session_id = context.store.resolve_chat_session_id(project_id, user, chat_session_id)
    emit_progress(progress_callback, "generation.completed", "Patch approval handled", status="completed")
    return {
      "generation": patch_payload["generation"],
      "files": patch_payload["files"],
      "patch_approval": patch_payload.get("patch_approval"),
      "chat_session_id": resolved_chat_session_id,
    }
  emit_progress(
    progress_callback,
    "run.locked",
    "Reserved this project for the active agent run",
    status="completed",
    detail={"run_id": getattr(active_run, "run_id", None), "project_id": project_id},
  )
  resolved_chat_session_id = None
  if hasattr(context.store, "resolve_chat_session_id"):
    resolved_chat_session_id = context.store.resolve_chat_session_id(project_id, user, chat_session_id)
  raise_if_project_run_cancelled(active_run)
  emit_progress(progress_callback, "project.loading", "Loading project and permissions")
  trace_print("ENTER", file=__file__, class_name="-", function="project_load", project_id=project_id)
  project = context.store.get_project(project_id, user)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")
  trace_print("EXIT", file=__file__, class_name="-", function="project_load", project_name=project.get("name"))
  emit_progress(
    progress_callback,
    "project.loaded",
    f"Loaded project: {project['name']}",
    status="completed",
    detail={"project_id": project_id},
  )
  raise_if_project_run_cancelled(active_run)
  try:
    workspace_sync = pull_linked_workspace_to_store(
      ToolRuntimeContext(store=context.store, settings=context.settings),
      user,
      project_id=project_id,
      source="generation_preflight",
    )
  except Exception as exc:
    workspace_sync = {}
    emit_progress(
      progress_callback,
      "local.sync.preflight.skipped",
      f"Skipped linked local folder preflight sync: {str(exc)[:180]}",
      status="completed",
      detail={"error": str(exc)[:500]},
    )
  if workspace_sync.get("local_sync"):
    emit_progress(
      progress_callback,
      "local.sync.completed",
      f"Loaded {workspace_sync.get('file_count', 0)} files from the linked local folder before planning",
      status="completed",
      detail=workspace_sync["local_sync"],
    )
  if is_simple_greeting_prompt(prompt):
    adaptive_route = classify_adaptive_request_route(prompt).to_dict()
    provider_label = "deterministic-tiny-chat"
    provider_model = "none"
    emit_progress(progress_callback, "routing.started", "Orchestrator handling tiny chat without a model call")
    generation = build_fast_greeting_generation(prompt)
    greeting_fast_path = "tiny_chat"
    emit_progress(
      progress_callback,
      "routing.completed",
      "Greeting handled without full model routing",
      status="completed",
      detail={
        "intent": "greeting",
        "next_action": "respond_and_collect_website_brief",
        "fast_path": greeting_fast_path,
        "adaptive_route": adaptive_route,
      },
    )
    emit_progress(
      progress_callback,
      "routing.adaptive.completed",
      "Adaptive route selected tiny chat",
      status="completed",
      detail=adaptive_route,
    )
    emit_progress(progress_callback, "conversation.completed", "Prepared greeting response without generating files", status="completed")
    if hasattr(context.store, "record_project_chat_message"):
      _record_project_chat_message_compat(
        context.store,
        project_id,
        user,
        role="user",
        content=prompt,
        metadata={
          "source": "generation_api",
          "selected_model": model,
          "request_id": telemetry.request_id if telemetry else None,
          "fast_path": f"greeting:{greeting_fast_path}",
          "adaptive_route": adaptive_route,
        },
        chat_session_id=resolved_chat_session_id,
      )
    run = context.store.create_generation_run(
      project_id,
      user,
      prompt=prompt,
      provider=provider_label,
      status="completed",
      response=generation,
    )
    update_telemetry_context(generation_run_id=run["id"])
    if hasattr(context.store, "record_project_chat_message"):
      greeting_memory, greeting_metadata = generation_model_chat_metadata(
        generation,
        base_metadata={
          "source": "generation_api",
          "provider": provider_label,
          "model": provider_model,
          "generation_run_id": run["id"],
          "intent": "greeting",
          "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
          "fast_path": f"greeting:{greeting_fast_path}",
          "adaptive_route": adaptive_route,
        },
      )
      _record_project_chat_message_compat(
        context.store,
        project_id,
        user,
        role="model",
        content=greeting_memory,
        metadata=greeting_metadata,
        chat_session_id=resolved_chat_session_id,
      )
    emit_progress(
      progress_callback,
      "generation.completed",
      "Greeting response recorded",
      status="completed",
      detail={"run_id": run["id"], "intent": "greeting", "fast_path": greeting_fast_path},
    )
    log_query_event(
      "query.completed",
      payload={"intent": "greeting", "file_count": 0, "fast_path": greeting_fast_path},
      provider=provider_label,
      model=provider_model,
      duration_ms=(monotonic() - started_at) * 1000,
    )
    _persist_memory_checkpoint_safe(
      context.store,
      user,
      project_id=project_id,
      chat_session_id=resolved_chat_session_id,
      generation_run_id=str(run.get("id") or ""),
      prompt=prompt,
      intent="greeting",
      outcome="completed",
      project_name=str(project.get("name") or ""),
      extra={"fast_path": greeting_fast_path},
    )
    return {
      "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
      "user_id": user.id,
      "chat_session_id": resolved_chat_session_id,
      "generation_run": run,
      "agent_run": None,
      "generation": generation,
      "files": context.store.list_files(project_id, user),
      "local_sync": None,
      "local_sync_error": None,
    }
  original_project_files = context.store.list_files(project_id, user)
  visible_original_project_files = visible_project_files(original_project_files)
  trace_print("EXIT", file=__file__, class_name="-", function="list_project_files", file_count=len(original_project_files), visible_file_count=len(visible_original_project_files))
  adaptive_route = classify_adaptive_request_route(
    prompt,
    project_files=visible_original_project_files,
    attachments=normalized_attachments,
  ).to_dict()
  effective_request_class = str(request_class or adaptive_route.get("route") or "").strip()
  credit_reservation: dict[str, Any] | None = None
  reservation_estimate = resolve_credit_reservation_estimate(effective_request_class, estimated_credit_reservation)
  if (
    reservation_estimate > 0
    and str(getattr(user, "role", "") or "").lower() != "admin"
    and hasattr(context.store, "reserve_ai_credits")
  ):
    credit_reservation = context.store.reserve_ai_credits(
      user.id,
      estimated_credits=reservation_estimate,
      project_id=project_id,
      request_id=telemetry.request_id if telemetry else None,
      route=effective_request_class,
      metadata={
        "model_policy": model_policy,
        "artifact_model": artifact_model,
        "selected_model": model,
      },
    )
    emit_progress(
      progress_callback,
      "usage.credits.reserved",
      f"Reserved {reservation_estimate:.4f} AI credits for this run",
      status="completed",
      detail={"credit_reservation": credit_reservation},
    )
  emit_progress(
    progress_callback,
    "routing.adaptive.preflight",
    f"Adaptive preflight selected {str(adaptive_route.get('route') or 'unknown').replace('_', ' ')}",
    status="completed",
    detail=adaptive_route,
  )
  small_code_fast_context = adaptive_route.get("route") == ADAPTIVE_ROUTE_SMALL_CODE
  raw_chat_history = _list_project_chat_messages_compat(
    context.store,
    project_id,
    user,
    limit=MAX_STORED_HISTORY_MESSAGES,
    chat_session_id=resolved_chat_session_id,
  ) if not small_code_fast_context else []
  raw_chat_history, chat_compaction = apply_chat_context_budget(raw_chat_history) if not small_code_fast_context else ([], {"compacted": False, "total_chars": 0})
  if chat_compaction.get("compacted"):
    emit_progress(
      progress_callback,
      "context.compacted",
      "Compacted chat history to stay within context budget",
      status="completed",
      detail=chat_compaction,
    )
  trace_print("EXIT", file=__file__, class_name="-", function="list_project_chat_messages", message_count=len(raw_chat_history))
  agents_md_block, agents_md_meta = ("", {"bootstrapped": False}) if small_code_fast_context else build_project_agents_md_block(visible_original_project_files)
  if agents_md_meta.get("bootstrapped"):
    emit_progress(
      progress_callback,
      "agents.md.bootstrapped",
      f"Using default project agent rules for {agents_md_meta.get('path')}",
      status="completed",
      detail=agents_md_meta,
    )
  if small_code_fast_context:
    project_context_contents = []
    emit_progress(
      progress_callback,
      "context.compacted",
      "Using code-only context for standalone code request",
      status="completed",
      detail={"mode": "small_code", "file_count": 0},
    )
  elif streaming_file_agent_enabled():
    project_context_contents = build_project_path_index_contents(visible_original_project_files)
    emit_progress(
      progress_callback,
      "context.compacted",
      "Using path-only project index for fast streaming updates",
      status="completed",
      detail={"mode": "path_index", "file_count": len(visible_original_project_files)},
    )
  else:
    project_context_contents = build_current_project_context_contents(visible_original_project_files)
  gemini_chat_history = project_context_contents + build_gemini_chat_history_contents(raw_chat_history)
  trace_print("EXIT", file=__file__, class_name="-", function="build_gemini_chat_history_contents", content_count=len(gemini_chat_history))
  enhancement_context = latest_enhancement_context(raw_chat_history)
  error_context = latest_error_context(raw_chat_history)
  prompt_for_agents = prompt.strip()
  if not small_code_fast_context and raw_chat_history:
    merged_prompt = enrich_website_modification_prompt(prompt_for_agents, raw_chat_history)
    if merged_prompt != prompt_for_agents:
      emit_progress(
        progress_callback,
        "context.chat_continuity",
        "Merged prior chat session requirements into this request",
        status="completed",
        detail={"prior_message_count": len(raw_chat_history)},
      )
      prompt_for_agents = merged_prompt
  greenfield_project = is_greenfield_codebase(visible_original_project_files)
  memory_context = ""
  if not small_code_fast_context:
    memory_context = build_agent_flow_memory_block(
      context.store,
      user,
      project_id=project_id,
      prompt=prompt_for_agents,
      chat_session_id=resolved_chat_session_id,
      project_name=str(project.get("name") or ""),
      files=visible_original_project_files,
      chat_messages=raw_chat_history,
      enhancement_context=enhancement_context,
      error_context=error_context,
      ideology_only=greenfield_project,
    )
  if greenfield_project and not small_code_fast_context:
    emit_progress(
      progress_callback,
      "context.greenfield",
      "Greenfield project — no existing code loaded; using platform patterns only",
      status="completed",
      detail={"mode": "ideology_only", "meaningful_file_count": 0},
    )
  workspace_files = [
    str(file_item.get("path") or "").strip()
    for file_item in meaningful_project_source_files(visible_original_project_files)
    if isinstance(file_item, dict) and str(file_item.get("path") or "").strip()
  ]
  skills_block = ""
  skill_resolution = None
  if not small_code_fast_context and user_opted_into_skills(prompt):
    skill_resolution = resolve_skill_request(
      prompt,
      workspace_root=_project_workspace_root(project),
      workspace_files=workspace_files,
      project_files=original_project_files,
      system_name=system_name,
      local_path=project.get("local_path"),
    )
    matched_skills = skill_resolution.selected
    skills_block = build_skills_prompt_block(matched_skills)
    if skill_resolution.has_explicit_mismatch:
      skills_block = build_skill_recommendation_block(
        selected_names=skill_resolution.explicit_names,
        rejected=skill_resolution.rejected,
        recommended=skill_resolution.recommended,
        missing_names=skill_resolution.missing_names,
        create_skill_suggestion=skill_resolution.create_skill_suggestion,
        reason=skill_resolution.reason,
      )
    if matched_skills:
      emit_progress(
        progress_callback,
        "skills.matched",
        f"Applied {len(matched_skills)} skill(s): {', '.join(skill.name for skill in matched_skills)}",
        status="completed",
        detail={"skills": [skill.to_dict() for skill in matched_skills]},
      )
    elif skill_resolution.has_explicit_mismatch:
      recommended_names = [skill.name for skill in skill_resolution.recommended]
      emit_progress(
        progress_callback,
        "skills.recommendation",
        (
          f"Selected skill is not relevant. Recommended: {', '.join('/' + name for name in recommended_names)}"
          if recommended_names
          else f"Selected skill is not relevant. Recommend creating a new skill: {skill_resolution.create_skill_suggestion}"
        ),
        status="completed",
        detail={
          "selected": skill_resolution.explicit_names,
          "rejected": [skill.to_dict() for skill in skill_resolution.rejected],
          "missing": skill_resolution.missing_names,
          "recommended": [skill.to_dict() for skill in skill_resolution.recommended],
          "create_skill_suggestion": skill_resolution.create_skill_suggestion,
        },
      )
  effective_prompt = prompt_for_agents.strip()
  if (
    not small_code_fast_context
    and confirmation_action not in {"confirm", "cancel"}
    and not looks_like_confirmation_reply(effective_prompt)
  ):
    effective_prompt = append_orchestrator_context(
      prompt_for_agents,
      error_context=error_context,
      enhancement_context=enhancement_context,
      skills_block=skills_block,
      episodic_context=memory_context,
      agents_md_block=agents_md_block,
    )
  if hasattr(context.store, "record_project_chat_message"):
    trace_print("ENTER", file=__file__, class_name="-", function="record_project_chat_message", role="user")
    user_metadata = {
      "source": "generation_api",
      "selected_model": model,
      "model_policy": model_policy,
      "artifact_model": artifact_model,
      "request_class": effective_request_class,
      "estimated_credit_reservation": reservation_estimate,
      "request_id": telemetry.request_id if telemetry else None,
      "adaptive_route": adaptive_route,
    }
    if normalized_attachments:
      try:
        from ..agents.prompting.attachments import chat_attachment_views
      except ImportError:
        from agents.prompting.attachments import chat_attachment_views
      user_metadata["attachments"] = chat_attachment_views(normalized_attachments)
    _record_project_chat_message_compat(
      context.store,
      project_id,
      user,
      role="user",
      content=prompt,
      metadata=user_metadata,
      chat_session_id=resolved_chat_session_id,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="record_project_chat_message", role="user")

  selected_model = normalize_generation_model(model)
  selected_artifact_model = normalize_generation_model(artifact_model) if artifact_model else selected_model
  raise_if_project_run_cancelled(active_run)
  gemini_provider_cls = _compatibility_export("GeminiProvider", GeminiProvider)
  generate_website_fn = _compatibility_export("generate_website", generate_website)
  persist_agent_runtime_output_fn = _compatibility_export("persist_agent_runtime_output", persist_agent_runtime_output)
  control_selected_model = resolve_control_model_for_request(selected_model)
  artifact_selected_model = selected_artifact_model
  control_provider = build_gemini_provider(
    gemini_provider_cls,
    model=control_selected_model,
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact_provider = build_gemini_provider(
    gemini_provider_cls,
    model=artifact_selected_model,
    provider_role=ARTIFACT_PROVIDER_ROLE,
    existing_provider=control_provider,
  )
  trace_print(
    "EXIT",
    file=__file__,
    class_name="GeminiProvider",
    function="__init__",
    control_model=control_selected_model,
    artifact_model=artifact_selected_model,
  )
  if hasattr(control_provider, "chat_history"):
    control_provider.chat_history = gemini_chat_history
  if artifact_provider is not control_provider and hasattr(artifact_provider, "chat_history"):
    artifact_provider.chat_history = gemini_chat_history
  control_source = "gemini_native"
  control_model = getattr(control_provider, "model", None) or getattr(getattr(control_provider, "client", None), "model", None)
  artifact_model = getattr(artifact_provider, "model", None) or getattr(getattr(artifact_provider, "client", None), "model", None)
  provider_label = "gemini-native-control-artifact"
  provider_model = f"gemini={artifact_model or control_model or selected_model or 'env-default'}"
  emit_progress(
    progress_callback,
    "provider.ready",
    "Using Gemini native control/artifact provider",
    status="completed",
    detail={
      "control_provider": control_provider.name,
      "control_model": control_model,
      "control_source": control_source,
      "artifact_provider": artifact_provider.name,
      "artifact_model": artifact_model,
    },
  )
  agent_run = context.store.create_agent_run(
    project_id,
    user,
    runtime="worktual-python-orchestrator",
    provider=provider_label,
    model=provider_model,
    input_payload=build_agent_run_input(
      project=project,
      prompt=prompt,
      provider=provider_label,
      model=provider_model,
      request_id=telemetry.request_id if telemetry else None,
    )
    | {
      "model_policy": model_policy,
      "artifact_model": artifact_model,
      "request_class": effective_request_class,
      "credit_reservation": credit_reservation,
    },
  )
  update_telemetry_context(agent_run_id=agent_run["id"])
  log_query_event(
    "agent_run.created",
    payload={"runtime": agent_run.get("runtime"), "status": agent_run.get("status")},
    provider=provider_label,
    model=provider_model,
  )
  emit_progress(
    progress_callback,
    "agent.run.started",
    "Started persistent agent runtime run",
    status="completed",
    detail={"agent_run_id": agent_run["id"]},
  )

  try:
    emit_progress(progress_callback, "generation.user_prompt", effective_prompt, status="running")
    emit_progress(progress_callback, "orchestrator.starting", "Starting backend agent orchestration")
    raise_if_project_run_cancelled(active_run)
    generation = generate_website_fn(
      effective_prompt,
      control_provider=control_provider,
      artifact_provider=artifact_provider,
      progress_callback=progress_callback,
      project_id=project_id,
      tool_context=ToolRuntimeContext(store=context.store, settings=context.settings),
      user=user,
      agent_run_id=agent_run["id"],
      graph_thread_id=graph_thread_id or f"{project_id}:{agent_run['id']}",
      resume_graph=resume_graph,
      confirmation_action=confirmation_action,
      attachments=normalized_attachments,
      chat_session_id=resolved_chat_session_id,
      project_name=str(project.get("name") or ""),
      patch_action=patch_action,
      adaptive_route=adaptive_route,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="generate_website", intent=generation.get("multi_agent_system", {}).get("intent"))
    raise_if_project_run_cancelled(active_run)
    agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime")
    if isinstance(agentic_runtime, dict):
      agentic_runtime["request_id"] = current_telemetry_context().request_id if current_telemetry_context() else None
    emit_progress(progress_callback, "orchestrator.completed", "Backend agent orchestration completed", status="completed")

    generated = generation.get("orchestration_flow", {}).get("generated_website", {})
    generated_files = []
    local_sync = None
    local_sync_error = None
    intent = generation.get("multi_agent_system", {}).get("intent")
    is_website_generation = intent in {"simple_code", "website_generation", "website_update"}
    agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime") or {}
    tool_source_of_truth = bool(agentic_runtime.get("tool_source_of_truth"))
    if is_website_generation:
      if intent == "website_generation":
        generated_files = visible_project_files(context.store.list_files(project_id, user))
      else:
        generated_files = visible_project_files(generated.get("files") or [])
        if not generated_files and tool_source_of_truth:
          generated_files = visible_project_files(context.store.list_files(project_id, user))
      raise_if_project_run_cancelled(active_run)
      diff_before_files = (
        original_files_for_generated_paths(visible_original_project_files, generated_files)
        if intent in {"simple_code", "website_update"} or tool_source_of_truth
        else visible_original_project_files
      )
      diff_compare_mode = "changed_only" if intent in {"simple_code", "website_update"} or tool_source_of_truth else "all"
      diff_payload = build_project_diff(diff_before_files, generated_files, compare_mode=diff_compare_mode)
      if diff_payload.get("file_count"):
        emit_progress(
          progress_callback,
          "file.diff.ready",
          f"Prepared code diff: {diff_payload.get('file_count', 0)} files, +{diff_payload.get('added', 0)} / -{diff_payload.get('removed', 0)}",
          status="completed",
          detail=diff_payload,
          audit_detail=redact_project_diff_for_audit(diff_payload),
        )
      if tool_source_of_truth:
        local_sync = agentic_runtime.get("local_sync")
        emit_progress(
          progress_callback,
          "files.persisted",
          f"{len(generated_files)} files were written by WRITE_PROJECT_FILES",
          status="completed",
          detail={
            "file_count": len(generated_files),
            "paths": [item["path"] for item in generated_files if item.get("path")],
            "files": generated_files,
            "source": "agent_tool",
          },
        )
        if should_sync_linked_local_folder(project, local_sync) and generated_files:
          try:
            raise_if_project_run_cancelled(active_run)
            emit_progress(progress_callback, "local.sync", "Checking linked local folder sync")
            local_sync = write_linked_project_files(
              context,
              project,
              generated_files,
              user,
              event_type="local.files.written",
              prune_missing=False,
            )
            if local_sync:
              emit_progress(
                progress_callback,
                "local.sync.completed",
                f"Wrote {local_sync.get('count', 0)} files to local disk",
                status="completed",
                detail=local_sync | {"source": "pipeline_tool_source_fallback"},
              )
              trace_print("EXIT", file=__file__, class_name="-", function="write_linked_project_files", file_count=local_sync.get("count"), source="tool_source_fallback")
            else:
              emit_progress(progress_callback, "local.sync.skipped", "No linked local folder for disk sync", status="completed")
          except LocalWorkspaceError as exc:
            local_sync_error = str(exc)
            emit_progress(progress_callback, "local.sync.failed", local_sync_error, status="failed")
      else:
        raise_if_project_run_cancelled(active_run)
        emit_progress(
          progress_callback,
          "files.persisting",
          f"Saving {len(generated_files)} generated files",
          detail={"file_count": len(generated_files)},
        )
        local_sync_ready = False
        if project.get("local_path"):
          try:
            raise_if_project_run_cancelled(active_run)
            emit_progress(progress_callback, "local.sync", "Checking linked local folder sync")
            local_sync = write_linked_project_files(
              context,
              project,
              generated_files,
              user,
              event_type="local.files.written",
              prune_missing=False,
            )
            local_sync_ready = bool(local_sync)
            if local_sync:
              emit_progress(
                progress_callback,
                "local.sync.completed",
                f"Wrote {local_sync.get('count', 0)} files to local disk",
                status="completed",
                detail=local_sync,
              )
          except LocalWorkspaceError as exc:
            local_sync_error = str(exc)
            emit_progress(progress_callback, "local.sync.failed", local_sync_error, status="failed")
            raise
        raise_if_project_run_cancelled(active_run)
        context.store.apply_generated_files(project_id, user, generated_files)
        trace_print("EXIT", file=__file__, class_name="-", function="apply_generated_files", file_count=len(generated_files))
        emit_progress(
          progress_callback,
          "files.persisted",
          f"Saved {len(generated_files)} files to the project",
          status="completed",
          detail={
            "file_count": len(generated_files),
            "paths": [item["path"] for item in generated_files if item.get("path")],
            "files": generated_files,
          },
        )
        try:
          from ..agents.code_index.incremental import maybe_reindex_after_persist
        except ImportError:
          from agents.code_index.incremental import maybe_reindex_after_persist
        maybe_reindex_after_persist(
          project_id,
          generated_files,
          changed_paths=[item["path"] for item in generated_files if item.get("path")],
        )
        if not local_sync_ready and project.get("local_path") and generated_files:
          synced_files = generated_files if intent == "simple_code" else visible_project_files(context.store.list_files(project_id, user))
          try:
            raise_if_project_run_cancelled(active_run)
            emit_progress(progress_callback, "local.sync", "Checking linked local folder sync")
            local_sync = write_linked_project_files(
              context,
              project,
              synced_files,
              user,
              event_type="local.files.written",
              prune_missing=False,
            )
            if local_sync:
              emit_progress(
                progress_callback,
                "local.sync.completed",
                f"Wrote {local_sync.get('count', 0)} files to local disk",
                status="completed",
                detail=local_sync,
              )
            else:
              emit_progress(progress_callback, "local.sync.skipped", "No linked local folder for disk sync", status="completed")
          except LocalWorkspaceError as exc:
            local_sync_error = str(exc)
            emit_progress(progress_callback, "local.sync.failed", local_sync_error, status="failed")
    else:
      emit_progress(progress_callback, "conversation.completed", "Prepared assistant reply without generating files", status="completed")

    raise_if_project_run_cancelled(active_run)
    run_label = "generation run" if is_website_generation else "assistant turn"
    emit_progress(progress_callback, "generation.recording", f"Recording {run_label}")
    run = context.store.create_generation_run(
      project_id,
      user,
      prompt=prompt,
      provider=provider_label,
      status="completed",
      response=generation,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="create_generation_run", run_id=run.get("id"))
    update_telemetry_context(generation_run_id=run["id"])
    emit_progress(
      progress_callback,
      "generation.completed",
      f"{run_label.capitalize()} recorded",
      status="completed",
      detail={"run_id": run["id"]},
    )
    emit_progress(progress_callback, "agent.runtime.persisting", "Persisting agent messages, tool calls, and memory")
    persist_agent_runtime_output_fn(
      context.store,
      agent_run_id=agent_run["id"],
      user=user,
      prompt=prompt,
      generation=generation,
      generation_run=run,
      files=generated_files,
      local_sync=local_sync,
      local_sync_error=local_sync_error,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="persist_agent_runtime_output")
    credit_reservation_result: dict[str, Any] | None = None
    if credit_reservation and hasattr(context.store, "complete_ai_credit_reservation"):
      request_id_for_credits = current_telemetry_context().request_id if current_telemetry_context() else ""
      actual_credits = reservation_estimate
      if hasattr(context.store, "sum_ai_credits_for_request") and request_id_for_credits:
        actual_credits = context.store.sum_ai_credits_for_request(user.id, request_id_for_credits)
      credit_reservation_result = context.store.complete_ai_credit_reservation(
        str(credit_reservation.get("id") or ""),
        actual_credits=actual_credits,
        status="completed",
      )
      emit_progress(
        progress_callback,
        "usage.credits.completed",
        f"Recorded {actual_credits:.4f} actual AI credits for this run",
        status="completed",
        detail={"credit_reservation": credit_reservation_result},
      )
    completed_agent_run = context.store.complete_agent_run(
      agent_run["id"],
      user,
      status="completed",
      output_payload={
        "generation_run_id": run["id"],
        "intent": generation.get("multi_agent_system", {}).get("intent"),
        "file_count": len(generated_files),
        "local_sync": local_sync,
        "local_sync_error": local_sync_error,
        "adaptive_route": adaptive_route,
        "model_policy": model_policy,
        "artifact_model": artifact_model,
        "request_class": effective_request_class,
        "credit_reservation": credit_reservation_result or credit_reservation,
      },
      generation_run_id=run["id"],
    )
    if hasattr(context.store, "link_automation_test_runs_to_generation"):
      context.store.link_automation_test_runs_to_generation(
        agent_run_id=str(agent_run["id"]),
        generation_run_id=str(run["id"]),
      )
    trace_print("EXIT", file=__file__, class_name="-", function="complete_agent_run", agent_run_id=completed_agent_run.get("id"))
    intent = generation.get("multi_agent_system", {}).get("intent") or "unknown"
    agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime") if isinstance(generation, dict) else {}
    agentic_runtime = agentic_runtime if isinstance(agentic_runtime, dict) else {}
    preview_status = _extract_preview_status_from_generation(generation)
    changed_paths = [str(item.get("path") or "") for item in generated_files if isinstance(item, dict)]
    runtime_diff = agentic_runtime.get("code_diff_summary") if isinstance(agentic_runtime.get("code_diff_summary"), dict) else {}
    runtime_validation = agentic_runtime.get("validation") if isinstance(agentic_runtime.get("validation"), dict) else {}
    runtime_visual_qa = agentic_runtime.get("visual_qa") if isinstance(agentic_runtime.get("visual_qa"), dict) else {}
    runtime_local_sync = agentic_runtime.get("local_sync") if isinstance(agentic_runtime.get("local_sync"), dict) else {}
    _persist_memory_checkpoint_safe(
      context.store,
      user,
      project_id=project_id,
      chat_session_id=resolved_chat_session_id,
      generation_run_id=str(run.get("id") or ""),
      prompt=prompt,
      intent=str(intent),
      outcome="completed",
      project_name=str(project.get("name") or ""),
      files=generated_files,
      changed_paths=changed_paths,
      preview_status=str(preview_status) if preview_status else None,
      extra={
        "generation_run_id": run.get("id"),
        "agent_run_id": completed_agent_run.get("id"),
        "requirement_trace": agentic_runtime.get("requirement_trace") or {},
        "selected_files": (agentic_runtime.get("requirement_trace") or {}).get("selected_files") if isinstance(agentic_runtime.get("requirement_trace"), dict) else [],
        "diff_summary": runtime_diff,
        "validation_status": runtime_validation.get("status"),
        "visual_qa_status": runtime_visual_qa.get("status"),
        "rollback_status": "restored" if agentic_runtime.get("rollback_restored") else "not_required",
        "token_budget_used": agentic_runtime.get("token_budget_used"),
        "route_selected": agentic_runtime.get("branch") or agentic_runtime.get("operation"),
        "route_reason": (agentic_runtime.get("requirement_trace") or {}).get("route_reason") if isinstance(agentic_runtime.get("requirement_trace"), dict) else "",
        "adaptive_route": adaptive_route,
        "local_sync_mode": runtime_local_sync.get("mode"),
      },
    )
    if hasattr(context.store, "record_project_chat_message"):
      trace_print("ENTER", file=__file__, class_name="-", function="record_project_chat_message", role="model")
      model_memory, model_metadata = generation_model_chat_metadata(
        generation,
        local_sync=local_sync,
        local_sync_error=local_sync_error,
        base_metadata={
          "source": "generation_api",
          "provider": provider_label,
          "model": provider_model,
          "generation_run_id": run["id"],
          "agent_run_id": completed_agent_run["id"],
          "intent": generation.get("multi_agent_system", {}).get("intent"),
          "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
          "adaptive_route": adaptive_route,
          "model_policy": model_policy,
          "artifact_model": artifact_model,
          "request_class": effective_request_class,
          "credit_reservation": credit_reservation_result or credit_reservation,
        },
      )
      _record_project_chat_message_compat(
        context.store,
        project_id,
        user,
        role="model",
        content=model_memory,
        metadata=model_metadata,
        chat_session_id=resolved_chat_session_id,
      )
      trace_print("EXIT", file=__file__, class_name="-", function="record_project_chat_message", role="model")
    emit_progress(
      progress_callback,
      "agent.runtime.persisted",
      "Agent runtime data persisted",
      status="completed",
      detail={"agent_run_id": completed_agent_run["id"]},
    )
    log_query_event(
      "query.completed",
      payload={
        "intent": generation.get("multi_agent_system", {}).get("intent"),
        "file_count": len(generated_files),
        "local_sync": local_sync,
        "adaptive_route": adaptive_route,
        "model_policy": model_policy,
        "artifact_model": artifact_model,
        "request_class": effective_request_class,
        "credit_reservation": credit_reservation_result or credit_reservation,
      },
      provider=provider_label,
      model=provider_model,
      duration_ms=(monotonic() - started_at) * 1000,
    )
    return {
      "request_id": current_telemetry_context().request_id if current_telemetry_context() else None,
      "user_id": user.id,
      "chat_session_id": resolved_chat_session_id,
      "generation_run": run,
      "agent_run": completed_agent_run,
      "generation": generation,
      "files": context.store.list_files(project_id, user),
      "local_sync": local_sync,
      "local_sync_error": local_sync_error,
    }
  except Exception as exc:
    failure = generation_failure_payload(exc)
    failure_detail = failure["detail"] | {
      "category": failure["category"],
      "code": failure["code"],
      "elapsed_seconds": round(monotonic() - started_at, 2),
    }
    emit_progress(
      progress_callback,
      "generation.failed",
      failure["user_message"],
      status="failed",
      detail=failure_detail,
    )
    try:
      if "agent_run" in locals() and isinstance(agent_run, dict):
        context.store.complete_agent_run(agent_run["id"], user, status="failed", error=failure["user_message"])
    except Exception:
      pass
    try:
      if "credit_reservation" in locals() and credit_reservation and hasattr(context.store, "complete_ai_credit_reservation"):
        request_id_for_credits = current_telemetry_context().request_id if current_telemetry_context() else ""
        actual_credits = 0.0
        if hasattr(context.store, "sum_ai_credits_for_request") and request_id_for_credits:
          actual_credits = context.store.sum_ai_credits_for_request(user.id, request_id_for_credits)
        context.store.complete_ai_credit_reservation(
          str(credit_reservation.get("id") or ""),
          actual_credits=actual_credits,
          status="failed",
        )
    except Exception:
      pass
    if "agent_run" in locals() and isinstance(agent_run, dict):
      failed_intent = "unknown"
      if "generation" in locals() and isinstance(generation, dict):
        failed_intent = str((generation.get("multi_agent_system") or {}).get("intent") or "unknown")
      if "resolved_chat_session_id" in locals() and "project" in locals():
        _persist_memory_checkpoint_safe(
          context.store,
          user,
          project_id=project_id,
          chat_session_id=resolved_chat_session_id,
          generation_run_id=str(run.get("id") or "") if "run" in locals() and isinstance(run, dict) else None,
          prompt=prompt,
          intent=failed_intent,
          outcome="failed",
          project_name=str(project.get("name") or ""),
          error_category=str(failure.get("category") or "generation_failed"),
          extra={"code": failure.get("code")},
        )
    log_query_event(
      "query.failed",
      status="failed",
      payload=failure,
      provider=provider_label,
      model=provider_model,
      duration_ms=(monotonic() - started_at) * 1000,
    )
    raise
