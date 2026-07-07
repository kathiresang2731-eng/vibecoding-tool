from __future__ import annotations

from typing import Any

from ....project_workspace import needs_vite_scaffold_repair
from ...fast_paths import backend_only_preview_skip_result, backend_only_visual_qa_skip_result, should_skip_preview_for_backend_only_change
from ...progress import (
  emit_gate_progress,
  emit_runtime_progress,
  is_missing_vite_entry_reason,
  is_unsafe_bare_react_reason,
  normalize_candidate_react_imports,
  preview_build_failure_reason,
  sync_generated_website_files_from_candidates,
)
from ...repair_tracking import record_repair_error
from ...state import append_step
from ...tooling import execute_tool_call, record_deterministic_repair_event
from ...values import list_value, object_value, text_or_default
from ...scaffolding import ensure_vite_scaffold_files, normalize_frontend_runtime_imports
from ...memory import persist_memory_checkpoint
from ..context import RuntimeActionContext
from .parts import (
  is_unresolved_preview_runtime_import_reason,
  normalize_preview_candidate_files,
)


def _linked_workspace_root(tool_context: Any, user: Any, project_id: str) -> str | None:
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "get_project"):
    return None
  project = store.get_project(project_id, user)
  if not isinstance(project, dict):
    return None
  workspace = str(project.get("local_path") or "").strip()
  return workspace or None


def handle_validate_project_artifact(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  emit_gate_progress(
    progress,
    gate="artifact_validation",
    phase="started",
    message="Running artifact validation gate",
    detail={"project_id": project_id},
  )
  validation_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="VALIDATE_PROJECT_ARTIFACT",
    arguments={"generated_website": object_value(state.get("generated_website"))},
  )
  state["validation_result"] = validation_result
  from backend.execution.gates import run_validation_gates
  gate_summary = run_validation_gates(
    validation_result=validation_result,
    candidate_files=list(state.get("candidate_files") or object_value(state.get("generated_website")).get("files") or []),
    workspace_root=_linked_workspace_root(tool_context, user, project_id),
  )
  state["gate_results"] = gate_summary
  failed_gate = gate_summary.get("failed_gate") if isinstance(gate_summary.get("failed_gate"), dict) else None
  if gate_summary.get("status") == "failed" and failed_gate:
    emit_runtime_progress(
      progress,
      "gate.validation.failed",
      str(failed_gate.get("message") or "Validation gate failed."),
      status="failed",
      detail=failed_gate,
    )
    record_repair_error(
      state,
      f"gate_failure:{failed_gate.get('gate')}: {failed_gate.get('message')}",
      source="validation_gate",
    )
  else:
    emit_runtime_progress(
      progress,
      "gate.validation.passed",
      "Validation gates passed",
      status="completed",
      detail=gate_summary,
    )
  append_step(state, agent, "validate_project_artifact", {"title": object_value(state.get("generated_website")).get("title")}, validation_result, tool_calls=["VALIDATE_PROJECT_ARTIFACT"])
  if should_skip_preview_for_backend_only_change(state):
    preview_result = backend_only_preview_skip_result(state)
    visual_qa_result = backend_only_visual_qa_skip_result(state)
    state["preview_result"] = preview_result
    state["preview"] = preview_result["version"]
    state["visual_qa_result"] = visual_qa_result
    append_step(
      state,
      "Preview Agent",
      "skip_frontend_preview_for_backend_only_change",
      {"changed_file_paths": list(state.get("changed_file_paths") or [])},
      preview_result,
    )
    append_step(
      state,
      "Visual QA Agent",
      "skip_visual_qa_for_backend_only_change",
      {"changed_file_paths": list(state.get("changed_file_paths") or [])},
      visual_qa_result,
    )


def handle_build_staged_project_preview(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  normalize_preview_candidate_files(state)
  state["candidate_files"] = state.get("candidate_files") or []
  sync_generated_website_files_from_candidates(state)
  if pending_materialization_files := __import__("backend.agents.agent_runtime.materialize", fromlist=["pending_materialization_files"]).pending_materialization_files(state):  # noqa: E501
    __import__("backend.agents.agent_runtime.materialize", fromlist=["materialize_candidate_files_incrementally"]).materialize_candidate_files_incrementally(  # noqa: E501
      state,
      tool_executor=tool_executor,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      progress=progress,
      agent=agent,
    )
  emit_runtime_progress(
    progress,
    "preview.prepared",
    "Prepared preview code changes",
    status="running",
    detail={"file_count": len(list(state.get("candidate_files") or []))},
  )
  preview_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="BUILD_STAGED_PROJECT_PREVIEW",
    arguments={"project_id": project_id, "files": list(state.get("candidate_files") or [])},
  )
  state["preview_result"] = preview_result
  state["preview"] = preview_result.get("version")
  append_step(state, agent, "build_staged_project_preview", {"project_id": project_id, "file_count": len(state.get("candidate_files") or [])}, preview_result, tool_calls=["BUILD_STAGED_PROJECT_PREVIEW"])
  build_status = object_value(preview_result.get("version")).get("status")
  if build_status != "ready":
    build_log = object_value(preview_result.get("version")).get("build_log") or "Preview build failed."
    repair_reason = preview_build_failure_reason(build_log)
    if is_missing_vite_entry_reason(repair_reason) and needs_vite_scaffold_repair(list(state.get("candidate_files") or [])):
      scaffolded_files, scaffold_paths = ensure_vite_scaffold_files(
        list(state.get("candidate_files") or []),
        title=text_or_default(object_value(state.get("generated_website")).get("title"), "Generated Website"),
      )
      if scaffold_paths:
        state["candidate_files"] = scaffolded_files
        sync_generated_website_files_from_candidates(state)
        state["preview_result"] = None
        state["preview"] = None
        state["visual_qa_result"] = None
        record_deterministic_repair_event(
          state,
          strategy="deterministic_vite_scaffold_rebuild",
          reason="Vite reported a missing index.html entry; injected scaffold and will rebuild once.",
          paths=scaffold_paths,
        )
        append_step(
          state,
          "Validation Agent",
          "normalize_vite_scaffold_for_preview_retry",
          {"reason": repair_reason, "missing_paths": scaffold_paths},
          {"status": "normalized", "paths": scaffold_paths, "classification": "artifact_scaffold_missing"},
        )
        return
      repair_reason = f"artifact_scaffold_missing: {repair_reason}"
    normalized_files, normalized_paths = normalize_candidate_react_imports(list(state.get("candidate_files") or []))
    if is_unsafe_bare_react_reason(repair_reason) and normalized_paths:
      state["candidate_files"] = normalized_files
      sync_generated_website_files_from_candidates(state)
      state["preview_result"] = None
      state["preview"] = None
      state["visual_qa_result"] = None
      append_step(
        state,
        "Validation Agent",
        "normalize_react_imports_for_preview_retry",
        {"reason": repair_reason, "paths": normalized_paths},
        {"status": "normalized", "paths": normalized_paths},
      )
      return
    runtime_import_files, runtime_import_paths = normalize_frontend_runtime_imports(list(state.get("candidate_files") or []))
    if is_unresolved_preview_runtime_import_reason(repair_reason) and runtime_import_paths:
      state["candidate_files"] = runtime_import_files
      sync_generated_website_files_from_candidates(state)
      state["preview_result"] = None
      state["preview"] = None
      state["visual_qa_result"] = None
      record_deterministic_repair_event(
        state,
        strategy="deterministic_frontend_runtime_import_rebuild",
        reason="Vite reported an unsupported frontend runtime package; rewired imports to platform shims and will rebuild once.",
        paths=runtime_import_paths,
      )
      append_step(
        state,
        "Validation Agent",
        "normalize_frontend_runtime_imports_for_preview_retry",
        {"reason": repair_reason, "paths": runtime_import_paths},
        {"status": "normalized", "paths": runtime_import_paths},
      )
      return
    record_repair_error(state, repair_reason, source="preview_build")
    persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key=f"build_error_{len(state['repair_errors'])}", kind="error", content=repair_reason[:2400], project_id=project_id)
