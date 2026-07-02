from __future__ import annotations

from typing import Any

from ...agentic_flow import generation_memory_content
from ...dynamic_agents import build_user_agent_registry, hydrate_registry_from_memories
from ...project_workspace import needs_vite_scaffold_repair
from ..constants import REAL_AGENT_RUNTIME_NAME
from ..fast_paths import backend_only_preview_skip_result, backend_only_visual_qa_skip_result, should_skip_preview_for_backend_only_change
from ..memory import build_project_state_memory, load_project_memory, persist_memory_checkpoint
from ..materialize import all_candidate_files, materialize_candidate_files_incrementally, pending_materialization_files
from ..progress import (
  emit_candidate_code_diff_progress,
  emit_gate_progress,
  emit_patch_applied_progress,
  emit_runtime_progress,
  is_missing_vite_entry_reason,
  is_unsafe_bare_react_reason,
  normalize_candidate_react_imports,
  preview_build_failure_reason,
  sync_generated_website_files_from_candidates,
)
from ..repair_tracking import record_repair_error
from ..runtime_summary import promote_dynamic_agents
from ...schema.json_safe import json_dumps_for_persistence, sanitize_for_persistence, scrub_runtime_objects_from_state
from ..scaffolding import RUNTIME_IMPORT_SHIM_PATHS, ensure_tailwind_runtime_files, ensure_vite_scaffold_files, normalize_frontend_runtime_imports
from ..state import append_step, record_agent_message
from ..targeted_updates import build_project_file_keyword_index
from ..tooling import execute_tool_call, record_deterministic_repair_event
from ..values import list_value, object_value, text_or_default
from ..file_ops import project_files_to_tool_files

try:
  from ...patch_approval import require_patch_approval_before_commit
except ImportError:
  from patch_approval import require_patch_approval_before_commit
from .context import RuntimeActionContext


INTERACTION_PROBLEM_TERMS = (
  "not working",
  "doesn't work",
  "does not work",
  "is not working",
  "not clickable",
  "can't click",
  "cannot click",
  "nothing happens",
  "broken",
)

INTERACTION_TARGET_TERMS = (
  "button",
  "click",
  "clicked",
  "clicking",
  "fix the action",
  "fix action",
  "handler",
  "submit",
  "dropdown",
  "modal",
  "toggle",
)

INTERACTION_CODE_MARKERS = (
  "onClick",
  "onSubmit",
  "onChange",
  "addEventListener",
  "preventDefault",
  "setCurrent",
  "setActive",
  "setShow",
  "setOpen",
  "navigate(",
  "window.location",
  "href=",
  "role=\"button\"",
)

VISUAL_QA_REQUIRED_TERMS = (
  "layout",
  "responsive",
  "mobile",
  "desktop",
  "alignment",
  "align",
  "overlap",
  "overflow",
  "scroll",
  "color",
  "theme",
  "dark",
  "light",
  "style",
  "design",
  "spacing",
  "padding",
  "margin",
  "font",
  "text visible",
  "not visible",
)


def build_project_read_result(ctx: RuntimeActionContext) -> dict[str, Any]:
  read_result = execute_tool_call(
    ctx.state,
    tool_executor=ctx.tool_executor,
    tool_context=ctx.tool_context,
    user=ctx.user,
    agent=ctx.agent,
    name="READ_PROJECT_FILES",
    arguments={"project_id": ctx.project_id},
  )
  file_index = build_project_file_keyword_index(project_files_to_tool_files(read_result.get("files")))
  read_result["file_index"] = file_index
  return read_result


def apply_project_read_result(ctx: RuntimeActionContext, read_result: dict[str, Any]) -> None:
  state = ctx.state
  file_index = read_result.get("file_index") or []
  state["project_file_index"] = file_index
  state["read_result"] = read_result
  local_sync = read_result.get("local_sync") if isinstance(read_result.get("local_sync"), dict) else None
  append_step(
    state,
    ctx.agent,
    "read_project_files",
    {"project_id": ctx.project_id},
    {
      "file_count": read_result.get("file_count", 0),
      "indexed_file_count": len(file_index),
      "source": "linked_local_workspace" if local_sync else "backend_project_store",
      "local_sync": local_sync,
    },
    tool_calls=["READ_PROJECT_FILES"],
  )
  source_note = " from the linked local workspace" if local_sync else ""
  record_agent_message(
    state,
    from_agent=ctx.agent,
    to_agent="Supervisor Agent",
    content=f"Loaded {read_result.get('file_count', 0)} existing project files{source_note}.",
    action=ctx.action,
  )


def build_project_memory_result(ctx: RuntimeActionContext) -> dict[str, Any]:
  return load_project_memory(
    ctx.state,
    tool_executor=ctx.tool_executor,
    tool_context=ctx.tool_context,
    user=ctx.user,
    project_id=ctx.project_id,
    progress=ctx.progress,
  )


def apply_project_memory_result(ctx: RuntimeActionContext, memory_result: dict[str, Any]) -> None:
  state = ctx.state
  state["memory_result"] = memory_result
  store = getattr(ctx.tool_context, "store", None)
  registry = build_user_agent_registry(store, ctx.user)
  hydrated_agent_ids = hydrate_registry_from_memories(memory_result.get("memories"), registry=registry)
  ctx.runtime_objects["dynamic_agent_registry"] = registry
  if hydrated_agent_ids:
    state["dynamic_agent_registry"] = registry.snapshot(agent_ids=hydrated_agent_ids)
    append_step(
      state,
      ctx.agent,
      "hydrate_dynamic_agent_registry",
      {"memory_count": memory_result.get("memory_count", 0)},
      {"hydrated_agent_ids": hydrated_agent_ids},
    )
  record_agent_message(
    state,
    from_agent=ctx.agent,
    to_agent="Supervisor Agent",
    content=f"Loaded {memory_result.get('memory_count', 0)} memory items.",
    action=ctx.action,
  )


def handle_read_project_files(ctx: RuntimeActionContext) -> None:
  apply_project_read_result(ctx, build_project_read_result(ctx))


def handle_load_project_memory(ctx: RuntimeActionContext) -> None:
  apply_project_memory_result(ctx, build_project_memory_result(ctx))


def handle_parallel_project_bootstrap(ctx: RuntimeActionContext) -> None:
  from ..parallel_actions import run_parallel_project_bootstrap

  parallel_result = run_parallel_project_bootstrap(ctx)
  apply_project_read_result(ctx, object_value(parallel_result.get("read_result")))
  apply_project_memory_result(ctx, object_value(parallel_result.get("memory_result")))
  append_step(
    ctx.state,
    ctx.agent,
    "parallel_project_bootstrap",
    {"project_id": ctx.project_id},
    {
      "parallel_execution_engine": parallel_result.get("parallel_execution_engine"),
      "file_count": object_value(parallel_result.get("read_result")).get("file_count", 0),
      "memory_count": object_value(parallel_result.get("memory_result")).get("memory_count", 0),
    },
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
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
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
  try:
    from ....execution.gates import run_validation_gates
  except ImportError:
    from execution.gates import run_validation_gates
  gate_summary = run_validation_gates(
    validation_result=validation_result,
    candidate_files=list(state.get("candidate_files") or object_value(state.get("generated_website")).get("files") or []),
    workspace_root=_linked_workspace_root(tool_context, user, project_id),
  )
  state["gate_results"] = gate_summary
  failed_gate = gate_summary.get("failed_gate") if isinstance(gate_summary.get("failed_gate"), dict) else None
  if gate_summary.get("status") == "failed" and failed_gate:
    emit_gate_progress(
      progress,
      gate=str(failed_gate.get("gate") or "validation"),
      phase="failed",
      message=str(failed_gate.get("message") or "Validation gate failed."),
      detail=failed_gate,
    )
    record_repair_error(
      state,
      f"gate_failure:{failed_gate.get('gate')}: {failed_gate.get('message')}",
      source="validation_gate",
    )
  else:
    emit_gate_progress(
      progress,
      gate="validation_pipeline",
      phase="passed",
      message="Validation gates passed",
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
  return

def handle_build_staged_project_preview(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  normalize_preview_candidate_files(state)
  state["candidate_files"] = all_candidate_files(state)
  sync_generated_website_files_from_candidates(state)
  if pending_materialization_files(state):
    materialize_candidate_files_incrementally(
      state,
      tool_executor=tool_executor,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      progress=progress,
      agent=agent,
    )
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="preview_candidate_prepared",
    message_prefix="Prepared preview code changes",
  )
  preview_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="BUILD_STAGED_PROJECT_PREVIEW",
    arguments={"project_id": project_id, "files": all_candidate_files(state)},
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
  return


def is_unresolved_preview_runtime_import_reason(reason: str) -> bool:
  lowered = str(reason or "").lower()
  if "failed to resolve import" not in lowered and "rollup failed to resolve import" not in lowered:
    return False
  return any(module_name.lower() in lowered for module_name in RUNTIME_IMPORT_SHIM_PATHS)


def normalize_preview_candidate_files(
  state: dict[str, Any],
  *,
  agent: str = "Validation Agent",
  record_steps: bool = True,
) -> list[str]:
  touched_paths: list[str] = []
  title = text_or_default(object_value(state.get("generated_website")).get("title"), "Generated Website")
  files = list(state.get("candidate_files") or [])

  scaffolded_files, scaffold_paths = (files, [])
  if needs_vite_scaffold_repair(files):
    scaffolded_files, scaffold_paths = ensure_vite_scaffold_files(files, title=title)
  if scaffold_paths:
    state["candidate_files"] = scaffolded_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(scaffold_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_vite_scaffold_normalization",
        reason="Added missing Vite scaffold files before staged preview build.",
        paths=scaffold_paths,
      )
      append_step(
        state,
        agent,
        "normalize_vite_scaffold_before_preview",
        {"missing_paths": scaffold_paths},
        {"status": "normalized", "paths": scaffold_paths},
      )
    files = scaffolded_files

  tailwind_files, tailwind_paths = ensure_tailwind_runtime_files(files)
  if tailwind_paths:
    state["candidate_files"] = tailwind_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(tailwind_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_tailwind_runtime_normalization",
        reason="Generated source used Tailwind utilities without a complete Tailwind runtime scaffold.",
        paths=tailwind_paths,
      )
      append_step(
        state,
        agent,
        "normalize_tailwind_runtime_before_preview",
        {"paths": tailwind_paths},
        {"status": "normalized", "paths": tailwind_paths},
      )
    files = tailwind_files

  normalized_files, normalized_paths = normalize_candidate_react_imports(files)
  if normalized_paths:
    state["candidate_files"] = normalized_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(normalized_paths)
    if record_steps:
      append_step(
        state,
        agent,
        "normalize_react_imports_before_preview",
        {"paths": normalized_paths},
        {"status": "normalized", "paths": normalized_paths},
      )
    files = normalized_files

  runtime_import_files, runtime_import_paths = normalize_frontend_runtime_imports(files)
  if runtime_import_paths:
    state["candidate_files"] = runtime_import_files
    sync_generated_website_files_from_candidates(state)
    touched_paths.extend(runtime_import_paths)
    if record_steps:
      record_deterministic_repair_event(
        state,
        strategy="deterministic_frontend_runtime_import_normalization",
        reason="Generated source imported preview runtime packages that are not installed in the workspace.",
        paths=runtime_import_paths,
      )
      append_step(
        state,
        agent,
        "normalize_frontend_runtime_imports_before_preview",
        {"paths": runtime_import_paths},
        {"status": "normalized", "paths": runtime_import_paths},
      )
  return touched_paths


def handle_run_preview_visual_qa(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  try:
    from ....visual_qa import build_automated_test_scope
  except ImportError:
    from visual_qa import build_automated_test_scope
  candidate_files = [item for item in list_value(state.get("candidate_files")) if isinstance(item, dict)]
  test_scope = build_automated_test_scope(
    candidate_files,
    changed_paths=[str(path) for path in list_value(state.get("changed_file_paths")) if str(path).strip()],
    operation=text_or_default(state.get("operation"), "generate"),
    prompt=text_or_default(state.get("prompt"), ""),
  )
  state["automated_test_scope"] = test_scope

  interaction_reason = interaction_fix_verification_reason(state)
  if interaction_reason:
    visual_qa_result = {
      "status": "failed",
      "mode": "static_interaction_verification",
      "warnings": [interaction_reason],
    }
    state["visual_qa_result"] = visual_qa_result
    record_repair_error(state, interaction_reason, source="visual_qa")
    append_step(
      state,
      agent,
      "verify_requested_interaction_fix",
      {"project_id": project_id, "changed_file_paths": list(state.get("changed_file_paths") or [])},
      visual_qa_result,
    )
    persist_memory_checkpoint(
      state,
      tool_context=tool_context,
      user=user,
      namespace="agent",
      key=f"interaction_qa_error_{len(state['repair_errors'])}",
      kind="error",
      content=interaction_reason[:2400],
      project_id=project_id,
    )
    return

  static_skip_reason = small_scoped_update_static_qa_reason(state) if not test_scope.get("visual_expected") else ""
  if static_skip_reason:
    visual_qa_result = {
      "status": "passed",
      "mode": "static_fast_scoped_update_qa",
      "browser_rendered": False,
      "checks": [
        {"name": "vite_build", "status": "passed", "detail": "Staged preview build completed before commit."},
        {"name": "scope", "status": "passed", "detail": static_skip_reason},
      ],
      "warnings": [],
    }
    state["visual_qa_result"] = visual_qa_result
    append_step(
      state,
      agent,
      "run_static_fast_scoped_update_qa",
      {"project_id": project_id, "changed_file_paths": list(state.get("changed_file_paths") or [])},
      visual_qa_result,
    )
    return

  preview = object_value(state.get("preview"))
  emit_runtime_progress(
    progress,
    "gate.visual_qa.running",
    "Running preview visual QA on staged build",
    status="running",
    detail={"preview_status": preview.get("status"), "preview_url": preview.get("preview_url")},
  )
  visual_qa_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="RUN_PREVIEW_VISUAL_QA",
    arguments={
      "project_id": project_id,
      "status": text_or_default(preview.get("status"), "unknown"),
      "preview_url": text_or_default(preview.get("preview_url"), ""),
      "build_log": text_or_default(preview.get("build_log"), ""),
      "operation": "update" if text_or_default(state.get("operation"), "generate") == "update" else "generation",
      "scope": text_or_default(test_scope.get("scope"), "full"),
      "chat_session_id": text_or_default(state.get("chat_session_id"), ""),
      "agent_run_id": text_or_default(state.get("agent_run_id"), ""),
      "project_version_id": text_or_default(preview.get("id") or preview.get("version_id"), ""),
      "route": text_or_default(list_value(test_scope.get("affected_routes"))[0] if list_value(test_scope.get("affected_routes")) else "/", "/"),
      "changed_paths": list_value(test_scope.get("changed_paths")),
      "affected_routes": list_value(test_scope.get("affected_routes")),
      "router_mode": text_or_default(test_scope.get("router_mode"), "hash"),
    },
  )
  state["visual_qa_result"] = visual_qa_result
  if object_value(visual_qa_result).get("status") != "passed":
    warnings = visual_qa_result.get("warnings") if isinstance(visual_qa_result, dict) else None
    layout_issues = visual_qa_result.get("layout_issues") if isinstance(visual_qa_result, dict) else None
    viewport_results = visual_qa_result.get("viewport_results") if isinstance(visual_qa_result, dict) else None
    reason = visual_qa_failure_reason(visual_qa_result, warnings)
    record_repair_error(state, reason or "Preview visual QA did not pass.", source="visual_qa")
    emit_runtime_progress(
      progress,
      "gate.visual_qa.failed",
      reason or "Preview visual QA did not pass",
      status="failed",
      detail={
        "status": object_value(visual_qa_result).get("status"),
        "warnings": warnings or [],
        "layout_checked": object_value(visual_qa_result).get("layout_checked"),
        "layout_severity": object_value(visual_qa_result).get("severity"),
        "layout_issues": layout_issues if isinstance(layout_issues, list) else [],
        "viewport_results": viewport_results if isinstance(viewport_results, list) else [],
        "category": "visual_qa",
        "code": "visual_qa_failed",
        "user_message": "Staged preview visual QA failed. No generated files were committed.",
        "suggested_actions": [
          "Open the preview and describe what looks wrong.",
          "Ask the agent to fix layout, styling, or missing sections.",
        ],
      },
    )
  else:
    emit_runtime_progress(
      progress,
      "gate.visual_qa.passed",
      "Preview visual QA passed",
      status="completed",
      detail={
        "mode": visual_qa_result.get("mode") if isinstance(visual_qa_result, dict) else None,
        "browser_rendered": visual_qa_result.get("browser_rendered") if isinstance(visual_qa_result, dict) else False,
      },
    )
  append_step(
    state,
    agent,
    "run_preview_visual_qa",
    {"project_id": project_id, "preview_status": preview.get("status")},
    visual_qa_result,
    tool_calls=["RUN_PREVIEW_VISUAL_QA"],
  )
  return


def visual_qa_failure_reason(visual_qa_result: Any, warnings: Any) -> str:
  result = object_value(visual_qa_result)
  warning_text = "; ".join(str(item) for item in warnings if isinstance(item, str)) if isinstance(warnings, list) else ""
  severity = text_or_default(result.get("severity"), "")
  issues = [item for item in list_value(result.get("layout_issues")) if isinstance(item, dict)]
  if not issues:
    return warning_text

  details: list[str] = []
  for issue in issues[:6]:
    viewport = text_or_default(issue.get("viewport"), "unknown viewport")
    issue_type = text_or_default(issue.get("type"), "layout_issue")
    message = text_or_default(issue.get("message"), "")
    element = object_value(issue.get("element"))
    selector = text_or_default(element.get("selector"), "")
    text = text_or_default(element.get("text"), "")
    target = selector or text[:80]
    detail = f"{viewport}: {issue_type}"
    if target:
      detail = f"{detail} at {target}"
    if message:
      detail = f"{detail} ({message})"
    details.append(detail)
  prefix = warning_text or "Preview layout QA failed."
  severity_text = f" Severity: {severity}." if severity else ""
  return f"{prefix}{severity_text} Layout issues: {' | '.join(details)}"


def interaction_fix_verification_reason(state: dict[str, Any]) -> str:
  prompt = text_or_default(state.get("prompt"), "").lower()
  has_problem_signal = any(term in prompt for term in INTERACTION_PROBLEM_TERMS)
  has_interaction_target = any(term in prompt for term in INTERACTION_TARGET_TERMS)
  if not has_problem_signal or not has_interaction_target:
    return ""
  changed_paths = set(list_value(state.get("changed_file_paths")))
  candidate_files = [
    item
    for item in list_value(state.get("candidate_files"))
    if isinstance(item, dict) and text_or_default(item.get("path"), "") in changed_paths
  ]
  changed_text = "\n".join(text_or_default(item.get("content"), "") for item in candidate_files)
  if any(marker in changed_text for marker in INTERACTION_CODE_MARKERS):
    return ""
  return (
    "Requested interaction/button fix did not add or modify detectable event wiring "
    "(handler, state change, navigation, submit, toggle, or link behavior). "
    "Repair the actual clicked interaction instead of changing only static UI."
  )


def small_scoped_update_static_qa_reason(state: dict[str, Any]) -> str:
  analysis = object_value(state.get("update_analysis"))
  if text_or_default(analysis.get("scope"), "small") != "small":
    return ""
  if text_or_default(analysis.get("update_mode"), "") not in {"targeted_patch", "bug_fix"}:
    return ""
  prompt = text_or_default(state.get("prompt"), "").lower()
  if any(term in prompt for term in VISUAL_QA_REQUIRED_TERMS):
    return ""
  changed_paths = list_value(state.get("changed_file_paths"))
  if len(changed_paths) > 2:
    return ""
  return "Small targeted/bug update verified with static scope checks; browser visual QA skipped for speed."

def handle_materialize_candidate_files(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  normalize_preview_candidate_files(state, agent=agent)
  state["candidate_files"] = all_candidate_files(state)
  sync_generated_website_files_from_candidates(state)
  materialize_candidate_files_incrementally(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
    agent=agent,
  )
  append_step(
    state,
    agent,
    "materialize_candidate_files",
    {"file_count": len(list_value(state.get("candidate_files")))},
    {
      "files_materialized": bool(state.get("files_materialized")),
      "materialized_file_paths": list_value(state.get("materialized_file_paths")),
      "local_sync": state.get("local_sync"),
    },
    tool_calls=[],
  )


def handle_write_project_files(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  if state.get("files_materialized"):
    emit_runtime_progress(
      progress,
      "files.persisted",
      "Project files are already available in the workspace",
      status="completed",
      detail={"file_count": len(list(state.get("candidate_files") or [])), "skipped": True},
    )
    state["committed"] = True
    return

  candidate_files = list(state.get("candidate_files") or [])
  if require_patch_approval_before_commit(
    state,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
    patch_action=state.get("patch_action"),
  ):
    return
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="commit_ready",
    message_prefix="Final code changes ready",
  )
  write_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="WRITE_PROJECT_FILES",
    arguments={"project_id": project_id, "files": candidate_files},
  )
  state["write_result"] = write_result
  state["committed"] = True
  state["local_sync"] = write_result.get("local_sync")
  emit_patch_applied_progress(
    state,
    progress,
    file_count=len(candidate_files),
    message_prefix="Committed code changes",
  )
  append_step(state, agent, "commit_staged_project_files", {"file_count": len(state.get("candidate_files") or [])}, write_result, tool_calls=["WRITE_PROJECT_FILES"])
  return

def handle_persist_project_memory(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  action = ctx.action
  control_provider = ctx.control_provider
  artifact_provider = ctx.artifact_provider
  prepared_sections = ctx.prepared_sections
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  start_time = ctx.start_time
  timeout_seconds = ctx.timeout_seconds
  progress = ctx.progress

  generated_website = object_value(state.get("generated_website"))
  promote_dynamic_agents(state, tool_context=tool_context, user=user, runtime_objects=ctx.runtime_objects)
  scrub_runtime_objects_from_state(state)
  dynamic_memory = sanitize_for_persistence(
    {
      "workflow": object_value(state.get("dynamic_workflow_plan")),
      "specialist_results": object_value(state.get("dynamic_specialist_results")),
      "registry": object_value(state.get("dynamic_agent_registry")),
      "repair_errors": list_value(state.get("repair_errors")),
    }
  )
  memory_output = {
    "memory_kind": "generation_summary",
    "content": (
      f"{generation_memory_content(generated_website, list(state.get('files') or []))}\n"
      f"Dynamic agent run: {json_dumps_for_persistence(dynamic_memory, context='memory.dynamic_run')[:6000]}"
    ),
  }
  persist_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="PERSIST_PROJECT_MEMORY",
    arguments={
      "project_id": project_id,
      "namespace": "agent",
      "key": "latest_generation_summary",
      "kind": "generation_summary",
      "content": memory_output["content"],
      "metadata": {
        "source": REAL_AGENT_RUNTIME_NAME,
        "preview_status": object_value(state.get("preview")).get("status"),
        "visual_qa_status": object_value(state.get("visual_qa_result")).get("status"),
      },
    },
  )
  state["memory"] = {**memory_output, "persist_result": persist_result}
  state["persisted_memory_events"].append(
    {
      "namespace": "agent",
      "key": "latest_generation_summary",
      "kind": "generation_summary",
      "content": memory_output["content"][:1200],
      "tool_call": "PERSIST_PROJECT_MEMORY",
    }
  )
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_dynamic_agent_registry",
    kind="agent_registry",
    content=object_value(state.get("dynamic_agent_registry")),
    project_id=project_id,
  )
  project_state_memory = sanitize_for_persistence(build_project_state_memory(state, project_id=project_id))
  state["latest_project_state_memory"] = project_state_memory
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_project_state",
    kind="project_state",
    content=project_state_memory,
    project_id=project_id,
  )
  append_step(state, agent, "persist_project_memory", {"title": generated_website.get("title"), "preview_status": object_value(state.get("preview")).get("status")}, state["memory"], tool_calls=["PERSIST_PROJECT_MEMORY"])
  return
