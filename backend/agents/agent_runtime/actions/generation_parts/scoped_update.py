from __future__ import annotations

import time

from backend.audit_logging import log_query_event

from ...errors import AgentRuntimeLoopError, ScopedUpdateGuardError
from ...file_ops import merge_project_file_changes, project_files_to_tool_files, tool_files_to_artifact_files
from ...patch_staging import stage_candidate_patches_via_apply_patch
from ...progress import emit_candidate_code_diff_progress, emit_runtime_progress, latest_repair_error, workflow_progress_detail
from ...repair_tracking import mark_repair_attempt_for_error
from ...scoped_update import scoped_update_generated_website, scoped_update_workflow_plan
from ...scoped_update.runtime import run_scoped_update_sequence
from ...state import append_step
from ...supervision import scoped_update_used_dynamic_agents, update_analysis_with_agentic_context
from ...targeted_updates import infer_project_title_from_files
from ...timeouts import remaining_runtime_seconds, scoped_update_sequence_timeout_seconds
from ...values import list_value, object_value
from ..context import RuntimeActionContext


def handle_scoped_update_agent(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
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

  update_analysis = object_value(state.get("update_analysis"))
  update_analysis_for_patch = update_analysis_with_agentic_context(update_analysis, state)
  existing_files = project_files_to_tool_files(object_value(state.get("read_result")).get("files"))
  previous_error = latest_repair_error(state)
  if previous_error:
    attempt = mark_repair_attempt_for_error(state, previous_error, agent=agent)
    if attempt["already_attempted"]:
      raise AgentRuntimeLoopError(
        "Repair stopped because the same failure signature already triggered a repair attempt "
        f"without producing a commit-safe result. Last issue: {previous_error[:900]}"
      )
    state["repair_attempts"] = int(state.get("repair_attempts") or 0) + 1
  sequence_timeout_seconds = scoped_update_sequence_timeout_seconds()
  runtime_remaining_seconds = max(1, int(remaining_runtime_seconds(start_time=start_time, timeout_seconds=timeout_seconds)))
  sequence_timeout_seconds = min(sequence_timeout_seconds, runtime_remaining_seconds)
  deadline_monotonic = time.monotonic() + sequence_timeout_seconds
  emit_runtime_progress(
    progress,
    "agent.loop.run_scoped_update_agent.model_started",
    f"Scoped Update Agent is generating a bounded patch with a {sequence_timeout_seconds}s timeout",
    status="running",
    detail={
      "timeout_seconds": sequence_timeout_seconds,
      "candidate_files": update_analysis_for_patch.get("candidate_files"),
      "task_count": len(list_value(update_analysis_for_patch.get("scoped_update_tasks"))) or 1,
    },
  )
  scope_expansion_events: list[dict[str, object]] = []

  def report_scope_expansion(event: dict[str, object]) -> None:
    scope_expansion_events.append(event)
    accepted_paths = [
      str(path)
      for path in list_value(event.get("accepted_paths"))
      if str(path).strip()
    ]
    emit_runtime_progress(
      progress,
      "agent.loop.scoped_update.scope_expanded",
      f"Scoped Update Agent added {', '.join(accepted_paths)} to the current task",
      status="running",
      detail=event,
    )

  try:
    scoped_result, changed_files, task_results = run_scoped_update_sequence(
      artifact_provider,
      prompt=state["prompt"],
      update_analysis=update_analysis_for_patch,
      existing_files=existing_files,
      code_search_matches=list_value(state.get("update_code_search_matches")),
      previous_error=previous_error,
      deadline_monotonic=deadline_monotonic,
      scope_expansion_callback=report_scope_expansion,
    )
  except Exception as exc:
    emit_runtime_progress(
      progress,
      "agent.loop.run_scoped_update_agent.failed",
      str(exc),
      status="failed",
      detail={
        "timeout_seconds": sequence_timeout_seconds,
        "candidate_files": update_analysis_for_patch.get("candidate_files"),
      },
    )
    raise
  changed_paths = [file_item["path"] for file_item in changed_files]
  if not changed_paths:
    message = (
      "Scoped update produced zero changed files. The update agent produced no file edits, "
      "so the existing website was preserved."
    )
    emit_runtime_progress(
      progress,
      "agent.loop.scoped_update.no_changes",
      message,
      status="failed",
      detail={
        "candidate_files": update_analysis_for_patch.get("candidate_files"),
        "task_count": len(task_results) or 1,
      },
    )
    log_query_event(
      "scoped_update.no_changes",
      payload={
        "update_mode": update_analysis.get("update_mode"),
        "scope": update_analysis.get("scope"),
        "candidate_files": update_analysis_for_patch.get("candidate_files"),
        "task_results": task_results,
      },
    )
    raise ScopedUpdateGuardError(message)
  staged_files, _patch_set = stage_candidate_patches_via_apply_patch(
    state,
    existing_files=existing_files,
    changed_files=changed_files,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    agent=agent,
    progress=progress,
    stage="scoped_update_staged",
  )
  candidate_files = merge_project_file_changes(existing_files, staged_files)
  title = infer_project_title_from_files(existing_files) or "Updated Website"
  generated_website = scoped_update_generated_website(
    title=title,
    prompt=state["prompt"],
    update_analysis=update_analysis,
    candidate_files=candidate_files,
    changed_paths=changed_paths,
  )
  state["scoped_update"] = {
    "status": "applied",
    "update_mode": update_analysis.get("update_mode"),
    "scope": update_analysis.get("scope"),
    "changed_file_paths": changed_paths,
    "task_count": len(task_results) or 1,
    "skipped_dynamic_agents": not scoped_update_used_dynamic_agents(state),
    "scope_expansion_count": len(scope_expansion_events),
    "scope_expansions": scope_expansion_events,
  }
  state["scoped_update_task_results"] = task_results
  scoped_workflow_plan = scoped_update_workflow_plan(update_analysis, changed_paths)
  if scoped_update_used_dynamic_agents(state):
    state["scoped_update_workflow_plan"] = scoped_workflow_plan
  else:
    state["dynamic_workflow_plan"] = scoped_workflow_plan
    state["dynamic_specialist_results"] = {
      "status": "skipped",
      "reason": "Scoped update mode bypassed the full dynamic-agent workflow.",
      "results": {},
      "candidate_changes": [],
      "rejected_candidate_changes": [],
    }
    state["dynamic_specialists_completed"] = True
  state["artifact_response"] = {"scoped_update": scoped_result, "generated_website": generated_website}
  state["generated_website"] = generated_website
  state["files"] = generated_website["files"]
  state["candidate_files"] = candidate_files
  state["changed_file_paths"] = changed_paths
  state["dynamic_patch_integrated"] = True
  state["validation_result"] = None
  state["preview_result"] = None
  state["preview"] = None
  state["visual_qa_result"] = None
  state["committed"] = False
  state["files_materialized"] = False
  state["materialized_file_paths"] = []
  state["materialized_file_signatures"] = {}
  state["repair_errors"] = []
  prepared_sections["scoped_update"] = state["scoped_update"]
  append_step(
    state,
    agent,
    "apply_scoped_update",
    {"update_analysis": update_analysis},
    state["scoped_update"],
  )
  emit_runtime_progress(
    progress,
    "plan.created",
    "Scoped update plan is ready",
    status="completed",
    detail=workflow_progress_detail(object_value(state.get("dynamic_workflow_plan"))),
  )
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="scoped_update_prepared",
    message_prefix="Prepared scoped code changes",
  )
  log_query_event(
    "scoped_update.applied",
    payload={
      "update_mode": update_analysis.get("update_mode"),
      "scope": update_analysis.get("scope"),
      "changed_file_paths": changed_paths,
      "task_results": task_results,
      "skipped_dynamic_agents": not scoped_update_used_dynamic_agents(state),
      "scope_expansions": scope_expansion_events,
    },
  )
  return
