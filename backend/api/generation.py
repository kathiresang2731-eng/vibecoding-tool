from __future__ import annotations

from time import monotonic
from typing import Any, Callable

from fastapi import HTTPException

try:
  from ..agent_runtime import build_agent_run_input, persist_agent_runtime_output
  from ..agent_tools import ToolRuntimeContext
  from ..audit_logging import current_telemetry_context, log_query_event, telemetry_scope, update_telemetry_context, RunTelemetryContext
  from ..code_diff import build_project_diff, redact_project_diff_for_audit
  from ..debug_trace import begin_backend_flow_capture, trace_function, trace_print
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
  from backend.agent_runtime import build_agent_run_input, persist_agent_runtime_output
  from backend.agent_tools import ToolRuntimeContext
  from backend.audit_logging import current_telemetry_context, log_query_event, telemetry_scope, update_telemetry_context, RunTelemetryContext
  from backend.code_diff import build_project_diff, redact_project_diff_for_audit
  from backend.debug_trace import begin_backend_flow_capture, trace_function, trace_print
  from backend.agents.chat_history import (
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
  from backend.agents.runtime_config import streaming_file_agent_enabled
  from backend.agents.memory.context import build_agent_flow_memory_block
  from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
  from backend.agents.project_workspace import is_greenfield_codebase, meaningful_project_source_files
  from backend.agents.generator import generate_website
  from backend.agents.requirement_confirmation import looks_like_confirmation_reply
  from backend.agentic.tools.handlers import pull_linked_workspace_to_store
  from backend.agents.orchestration.conversation import build_conversation_generation_response, deterministic_conversation_response
  from backend.agents.orchestration.state import GenerationPipelineState
  from backend.agents.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, DUAL_PROVIDER_ROLE, GeminiProvider
  from backend.local_workspace import LocalWorkspaceError
  from backend.runtime_control import runtime_cancellation_scope
  from backend.storage import StorageError, UserContext
  from backend.api.run_locks import acquire_project_run_lock, raise_if_project_run_cancelled

from .context import AppContext
from .failures import normalize_generation_model
from .local_workspaces import write_linked_project_files
from .progress import emit_progress
from .generation_parts import (
  _compatibility_export,
  _list_project_chat_messages_compat,
  _persist_memory_checkpoint_safe,
  _project_workspace_root,
  _record_project_chat_message_compat,
  append_orchestrator_context,
  build_gemini_provider,
  default_credit_reservation_for_route,
  is_hidden_project_file_path,
  original_files_for_generated_paths,
  print_project_workspace_snapshot,
  resolve_control_model_for_request,
  resolve_credit_reservation_estimate,
  should_sync_linked_local_folder,
  visible_project_files,
  extract_preview_status_from_generation,
)
from .generation_parts.failure import report_generation_failure
from .generation_parts.flow_trace import log_generation_flow_trace
from .generation_parts.preflight import prepare_generation_pipeline_inputs
from .generation_parts.resume import run_generation_resume
from .generation_parts.postflight import finalize_generation_success

try:
  from ..skills.injector import build_skill_recommendation_block, build_skills_prompt_block
  from ..skills.matcher import user_opted_into_skills
  from ..skills.runtime import resolve_skill_request
  from ..skills.agents_md import build_project_agents_md_block
  from ..agents.canonical_roles import compact_runtime_step_projection
except ImportError:
  from backend.skills.injector import build_skill_recommendation_block, build_skills_prompt_block
  from backend.skills.matcher import user_opted_into_skills
  from backend.skills.runtime import resolve_skill_request
  from backend.skills.agents_md import build_project_agents_md_block
  from backend.agents.canonical_roles import compact_runtime_step_projection


def _string_list(values: object) -> list[str]:
  if not isinstance(values, list):
    return []
  return [str(item).strip() for item in values if str(item or "").strip()]




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
  begin_backend_flow_capture()
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
  run: dict[str, Any] | None = None
  chat_topic_id: str | None = None
  topic_resolution: dict[str, Any] = {}
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
    from backend.api.usage_enforcement import assert_user_can_generate
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
      from backend.agents.prompting.attachments import normalize_prompt_attachments
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
      from backend.agents.patch_approval import resolve_patch_approval_turn
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
  selected_model = normalize_generation_model(model)
  selected_artifact_model = normalize_generation_model(artifact_model) if artifact_model else selected_model
  gemini_provider_cls = _compatibility_export("GeminiProvider", GeminiProvider)
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
  preflight = prepare_generation_pipeline_inputs(
    context=context,
    project_id=project_id,
    prompt=prompt,
    user=user,
    project=project,
    normalized_attachments=normalized_attachments,
    resolved_chat_session_id=resolved_chat_session_id,
    request_class=request_class,
    estimated_credit_reservation=estimated_credit_reservation,
    model=model,
    artifact_model=artifact_model,
    model_policy=model_policy,
    progress_callback=progress_callback,
    telemetry=telemetry,
    system_name=system_name,
    confirmation_action=confirmation_action,
    topic_llm_provider=control_provider,
  )
  original_project_files = preflight["original_project_files"]
  visible_original_project_files = preflight["visible_original_project_files"]
  adaptive_route = preflight["adaptive_route"]
  topic_resolution = preflight.get("topic_resolution") if isinstance(preflight.get("topic_resolution"), dict) else {}
  chat_topic_id = str(preflight.get("chat_topic_id") or topic_resolution.get("chat_topic_id") or "").strip() or None
  effective_request_class = preflight["effective_request_class"]
  credit_reservation = preflight["credit_reservation"]
  reservation_estimate = preflight["reservation_estimate"]
  small_code_fast_context = preflight["small_code_fast_context"]
  raw_chat_history = preflight["raw_chat_history"]
  chat_compaction = preflight["chat_compaction"]
  agents_md_block = preflight["agents_md_block"]
  agents_md_meta = preflight["agents_md_meta"]
  project_context_contents = preflight["project_context_contents"]
  gemini_chat_history = preflight["gemini_chat_history"]
  enhancement_context = preflight["enhancement_context"]
  error_context = preflight["error_context"]
  prompt_for_agents = preflight["prompt_for_agents"]
  greenfield_project = preflight["greenfield_project"]
  memory_context = preflight["memory_context"]
  workspace_files = preflight["workspace_files"]
  skills_block = preflight["skills_block"]
  skill_resolution = preflight["skill_resolution"]
  effective_prompt = preflight["effective_prompt"]
  log_generation_flow_trace(
    "conversation.flow.preflight",
    prompt=prompt,
    project_id=project_id,
    chat_session_id=resolved_chat_session_id,
    chat_topic_id=chat_topic_id,
    topic_resolution=topic_resolution,
    adaptive_route=adaptive_route,
    selected_files=[],
    project_files=visible_original_project_files[:200] if adaptive_route.get("use_project_context") else [],
    status="running",
    extra={
      "effective_prompt": effective_prompt,
      "chat_history_count": len(raw_chat_history),
      "greenfield_project": greenfield_project,
      "skill_requested": bool(skill_resolution),
      **(
        {}
        if adaptive_route.get("route") == "tiny_chat"
        else {"workspace_candidate_pool": workspace_files[:200]}
      ),
    },
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
      "chat_topic_id": chat_topic_id,
      "topic_resolution": topic_resolution,
    }
    if normalized_attachments:
      try:
        from ..agents.prompting.attachments import chat_attachment_views
      except ImportError:
        from backend.agents.prompting.attachments import chat_attachment_views
      user_metadata["attachments"] = chat_attachment_views(normalized_attachments)
    _record_project_chat_message_compat(
      context.store,
      project_id,
      user,
      role="user",
      content=prompt,
      metadata=user_metadata,
      chat_session_id=resolved_chat_session_id,
      chat_topic_id=chat_topic_id,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="record_project_chat_message", role="user")

  raise_if_project_run_cancelled(active_run)
  generate_website_fn = _compatibility_export("generate_website", generate_website)
  persist_agent_runtime_output_fn = _compatibility_export("persist_agent_runtime_output", persist_agent_runtime_output)
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
      chat_topic_id=chat_topic_id,
      project_name=str(project.get("name") or ""),
      patch_action=patch_action,
      adaptive_route=adaptive_route,
    )
    trace_print("EXIT", file=__file__, class_name="-", function="generate_website", intent=generation.get("multi_agent_system", {}).get("intent"))
    raise_if_project_run_cancelled(active_run)
    agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime")
    if isinstance(agentic_runtime, dict):
      agentic_runtime["request_id"] = current_telemetry_context().request_id if current_telemetry_context() else None
    generation_intent = generation.get("multi_agent_system", {}).get("intent")
    if (
      generation_intent == "website_update"
      and isinstance(agentic_runtime, dict)
      and (
        str(agentic_runtime.get("status") or "").lower() == "failed"
        or bool(agentic_runtime.get("no_code_changes"))
      )
    ):
      raise RuntimeError(
        str(agentic_runtime.get("output_text") or "").strip()
        or "Targeted update could not be applied safely because no file patch was produced."
      )
    emit_progress(progress_callback, "orchestrator.completed", "Backend agent orchestration completed", status="completed")

    generated = generation.get("orchestration_flow", {}).get("generated_website", {})
    generated_files = []
    local_sync = None
    local_sync_error = None
    intent = generation.get("multi_agent_system", {}).get("intent")
    is_website_generation = intent in {"simple_code", "document_artifact", "website_generation", "website_update"}
    agentic_runtime = generation.get("multi_agent_system", {}).get("agentic_runtime") or {}
    tool_source_of_truth = bool(agentic_runtime.get("tool_source_of_truth"))
    runtime_update_scope = agentic_runtime.get("update_scope") if isinstance(agentic_runtime.get("update_scope"), dict) else {}
    runtime_diagnostic_report = agentic_runtime.get("diagnostic_report") if isinstance(agentic_runtime.get("diagnostic_report"), dict) else {}
    routing_result_for_log = generation.get("multi_agent_system", {}).get("routing_result") if isinstance(generation.get("multi_agent_system"), dict) else {}
    target_resolution_for_log = routing_result_for_log.get("target_resolution") if isinstance(routing_result_for_log, dict) and isinstance(routing_result_for_log.get("target_resolution"), dict) else {}
    if is_website_generation:
      generated_files = visible_project_files(generated.get("files") or [])
      if not generated_files and tool_source_of_truth:
        generated_files = visible_project_files(context.store.list_files(project_id, user))
      workspace_snapshot = print_project_workspace_snapshot(
        stage="after_orchestration",
        project_id=project_id,
        project=project,
        files=visible_original_project_files,
        generated_files=generated_files,
        intent=str(intent or ""),
      )
      if not generated_files and not tool_source_of_truth:
        emit_progress(
          progress_callback,
          "files.missing",
          "Artifact execution returned zero generated files; nothing was saved",
          status="failed",
          detail={
            **workspace_snapshot,
            "tool_source_of_truth": False,
          },
        )
        raise RuntimeError(
          f"{str(intent or 'artifact').replace('_', ' ').title()} returned zero "
          f"generated files for project folder {workspace_snapshot['folder']}. "
          "No files were saved."
        )
      raise_if_project_run_cancelled(active_run)
      diff_before_files = (
        original_files_for_generated_paths(visible_original_project_files, generated_files)
        if intent in {"simple_code", "document_artifact", "website_update"} or tool_source_of_truth
        else visible_original_project_files
      )
      diff_compare_mode = "changed_only" if intent in {"simple_code", "document_artifact", "website_update"} or tool_source_of_truth else "all"
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
        local_sync_error = str(agentic_runtime.get("local_sync_error") or local_sync_error or "") or None
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
            "workspace": workspace_snapshot,
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
          detail={
            "file_count": len(generated_files),
            "paths": [item["path"] for item in generated_files if item.get("path")],
            "workspace": workspace_snapshot,
          },
        )
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
            "workspace": workspace_snapshot,
          },
        )
        try:
          from ..agents.code_index.incremental import maybe_reindex_after_persist
        except ImportError:
          from backend.agents.code_index.incremental import maybe_reindex_after_persist
        maybe_reindex_after_persist(
          project_id,
          generated_files,
          changed_paths=[item["path"] for item in generated_files if item.get("path")],
        )
        if project.get("local_path") and generated_files:
          synced_files = generated_files if intent in {"simple_code", "document_artifact"} else visible_project_files(context.store.list_files(project_id, user))
          try:
            raise_if_project_run_cancelled(active_run)
            emit_progress(progress_callback, "local.sync", "Writing saved project files to linked local folder")
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
            emit_progress(
              progress_callback,
              "local.sync.failed",
              local_sync_error,
              status="failed",
              detail={"project_saved": True, "file_count": len(generated_files), "error": local_sync_error},
            )
    else:
      emit_progress(progress_callback, "conversation.completed", "Prepared assistant reply without generating files", status="completed")

    requirement_trace = agentic_runtime.get("requirement_trace") if isinstance(agentic_runtime, dict) else {}
    project_files_for_log = []
    if intent in {"website_update", "website_generation", "simple_code"}:
      if intent == "website_update":
        scoped_paths = list(dict.fromkeys([
          *_string_list(target_resolution_for_log.get("resolved_files")),
          *_string_list(runtime_update_scope.get("target_files")),
          *_string_list(runtime_update_scope.get("candidate_files")),
          *_string_list(runtime_diagnostic_report.get("candidate_files")),
        ]))
        if scoped_paths:
          scoped_path_set = set(scoped_paths)
          project_files_for_log = [
            file_item
            for file_item in visible_original_project_files
            if str(file_item.get("path") or "").strip() in scoped_path_set
          ]
        else:
          project_files_for_log = visible_original_project_files[:200]
      else:
        project_files_for_log = visible_original_project_files[:200]
    elif intent == "project_info":
      project_context_for_log = routing_result_for_log.get("project_context") if isinstance(routing_result_for_log, dict) else {}
      selected_live_paths = []
      if isinstance(project_context_for_log, dict):
        selected_live_paths = [
          str(item.get("path") or "").strip()
          for item in (project_context_for_log.get("selected_live_files") or [])
          if isinstance(item, dict) and str(item.get("path") or "").strip()
        ]
      if selected_live_paths:
        selected_live_path_set = set(selected_live_paths)
        project_files_for_log = [
          file_item
          for file_item in visible_original_project_files
          if str(file_item.get("path") or "").strip() in selected_live_path_set
        ]
      else:
        project_files_for_log = visible_original_project_files[:200]

    selected_files_for_log = (requirement_trace.get("selected_files") if isinstance(requirement_trace, dict) else []) or []
    if intent == "website_update" and not selected_files_for_log:
      selected_files_for_log = list(dict.fromkeys([
        *_string_list(target_resolution_for_log.get("resolved_files")),
        *_string_list(runtime_update_scope.get("target_files")),
        *_string_list(runtime_update_scope.get("candidate_files")),
        *_string_list(runtime_diagnostic_report.get("target_files")),
        *_string_list(runtime_diagnostic_report.get("candidate_files")),
      ]))

    runtime_step_entries = (
      (agentic_runtime.get("steps") if isinstance(agentic_runtime.get("steps"), list) else None)
      or (
        generation.get("gemini_tool_calling_setup", {}).get("runtime_trace", {}).get("steps")
        if isinstance(generation.get("gemini_tool_calling_setup"), dict)
        and isinstance(generation.get("gemini_tool_calling_setup", {}).get("runtime_trace"), dict)
        else []
      )
      or []
    )
    runtime_projection_for_log = compact_runtime_step_projection(runtime_step_entries)

    log_generation_flow_trace(
      "conversation.flow.completed",
      prompt=prompt,
      project_id=project_id,
      chat_session_id=resolved_chat_session_id,
      chat_topic_id=chat_topic_id,
      topic_resolution=topic_resolution,
      routing_result=generation.get("multi_agent_system", {}).get("routing_result") if isinstance(generation.get("multi_agent_system"), dict) else {},
      adaptive_route=adaptive_route,
      selected_files=selected_files_for_log,
      generated_files=generated_files,
      project_files=project_files_for_log,
      provider=provider_label,
      model=provider_model,
      status="completed",
      extra={
        "intent": intent,
        "tool_source_of_truth": tool_source_of_truth,
        "local_sync_error": local_sync_error,
        "runtime_tool_sequence": (
          [
            str(call.get("name") or "").strip()
            for call in (agentic_runtime.get("tool_calls") if isinstance(agentic_runtime.get("tool_calls"), list) else [])
            if isinstance(call, dict) and str(call.get("name") or "").strip()
          ]
          if tool_source_of_truth
          else (
            generation.get("gemini_tool_calling_setup", {}).get("tool_call_sequence")
            if isinstance(generation.get("gemini_tool_calling_setup"), dict)
            else []
          )
        ) or [],
        "runtime_steps": runtime_projection_for_log["runtime_steps"],
        "runtime_internal_steps": runtime_projection_for_log["runtime_internal_steps"],
        "runtime_step_details": runtime_projection_for_log["runtime_step_details"],
        "runtime_phase_details": runtime_projection_for_log["runtime_phase_details"],
      },
    )

    raise_if_project_run_cancelled(active_run)
    return finalize_generation_success(
      context=context,
      user=user,
      project_id=project_id,
      project=project,
      prompt=prompt,
      generation=generation,
      generated_files=generated_files,
      local_sync=local_sync,
      local_sync_error=local_sync_error,
      provider_label=provider_label,
      provider_model=provider_model,
      progress_callback=progress_callback,
      started_at=started_at,
      resolved_chat_session_id=resolved_chat_session_id,
      model_policy=model_policy,
      artifact_model=artifact_model,
      effective_request_class=effective_request_class,
      adaptive_route=adaptive_route,
      topic_resolution=topic_resolution,
      chat_topic_id=chat_topic_id,
      credit_reservation=credit_reservation,
      reservation_estimate=reservation_estimate,
      agent_run=agent_run,
      run=run,
      persist_agent_runtime_output_fn=persist_agent_runtime_output_fn,
      visible_project_files=visible_project_files,
      original_project_files=original_project_files,
      intent=str(generation.get("multi_agent_system", {}).get("intent") or "unknown"),
      project_name=str(project.get("name") or ""),
    )
  except Exception as exc:
    report_generation_failure(
      context=context,
      user=user,
      project_id=project_id,
      project=project if "project" in locals() else None,
      prompt=prompt,
      generation=generation if "generation" in locals() else None,
      progress_callback=progress_callback,
      started_at=started_at,
      resolved_chat_session_id=resolved_chat_session_id,
      chat_topic_id=chat_topic_id,
      topic_resolution=topic_resolution,
      provider_label=provider_label,
      provider_model=provider_model,
      credit_reservation=credit_reservation if "credit_reservation" in locals() else None,
      agent_run=agent_run if "agent_run" in locals() else None,
      run=run if "run" in locals() else None,
      exc=exc,
    )
    raise
