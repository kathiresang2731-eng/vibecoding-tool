from __future__ import annotations

import time

try:
  from ....audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ..errors import AgentRuntimeLoopError
from ..file_ops import artifact_files_to_tool_files, merge_candidate_files_for_operation, merge_project_file_changes, project_files_to_tool_files, tool_files_to_artifact_files
from ..memory import persist_memory_checkpoint
from ..model_agents import run_code_agent
from ..patch_staging import stage_candidate_patches_via_apply_patch
from ..progress import emit_candidate_code_diff_progress, emit_runtime_progress, latest_repair_error, workflow_progress_detail
from ..repair_tracking import mark_repair_attempt_for_error, record_repair_error
from ..runtime_summary import record_dynamic_contribution_failure
from ..scoped_update import scoped_update_generated_website, scoped_update_workflow_plan
from ..scoped_update.runtime import run_scoped_update_sequence
from ..state import append_step
from ..supervision import scoped_update_used_dynamic_agents, update_analysis_with_agentic_context
from ..targeted_updates import infer_project_title_from_files
from ..timeouts import remaining_runtime_seconds, repair_runtime_min_remaining_seconds, scoped_update_sequence_timeout_seconds, should_skip_gemini_repair_for_budget
from ..tooling import validate_project_artifact_from_response
from ..values import list_value, object_value, text_or_default
from .context import RuntimeActionContext


def handle_scoped_update_agent(ctx: RuntimeActionContext) -> None:
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

def handle_code_or_repair_agent(ctx: RuntimeActionContext) -> None:
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

  previous_error = latest_repair_error(state)
  operation = text_or_default(state.get("operation"), "generate")
  brief = object_value(state.get("brief"))
  plan = object_value(state.get("plan"))
  if action == "RUN_REPAIR_AGENT":
    if previous_error:
      attempt = mark_repair_attempt_for_error(state, previous_error, agent=agent)
      if attempt["already_attempted"]:
        raise AgentRuntimeLoopError(
          "Repair stopped because the same failure signature already triggered a repair attempt "
          f"without producing a commit-safe result. Last issue: {previous_error[:900]}"
        )
    record_dynamic_contribution_failure(
      state,
      reason=previous_error or "Dynamic contribution triggered repair.",
      tool_context=tool_context,
      user=user,
      runtime_objects=ctx.runtime_objects,
    )
    state["repair_attempts"] = int(state.get("repair_attempts") or 0) + 1

  if action == "RUN_REPAIR_AGENT" and should_skip_gemini_repair_for_budget(start_time=start_time, timeout_seconds=timeout_seconds):
    repair_threshold = repair_runtime_min_remaining_seconds()
    budget_error = RuntimeError(
      "Skipped Gemini repair because less than "
      f"{repair_threshold}s remained in the runtime budget. "
      f"Previous error: {previous_error or 'unknown'}"
    )
    repair_reason = f"Code artifact validation failed: {budget_error}"
    record_repair_error(state, repair_reason, source="repair_budget")
    append_step(state, "Validation Agent", "validate_code_agent_output", {"action": action}, {"status": "failed", "reason": repair_reason[:1200]})
    persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key=f"artifact_error_{len(state['repair_errors'])}", kind="error", content=repair_reason[:2400], project_id=project_id)
    raise AgentRuntimeLoopError(repair_reason) from budget_error
  else:
    try:
      artifact_response = run_code_agent(
        artifact_provider,
        prompt=state["prompt"],
        operation=operation,
        brief=brief,
        plan=plan,
        prepared_sections={
          **prepared_sections,
          "ux_review": state.get("ux_review"),
          "accessibility_review": state.get("accessibility_review"),
        },
        read_result=object_value(state.get("read_result")),
        memory_result=object_value(state.get("memory_result")),
        previous_error=previous_error,
      )
      generated_website = validate_project_artifact_from_response(artifact_response)
      state["artifact_fallback"] = None
    except Exception as exc:
      repair_reason = f"Code artifact validation failed: {exc}"
      record_repair_error(state, repair_reason, source="artifact_validation")
      append_step(state, "Validation Agent", "validate_code_agent_output", {"action": action}, {"status": "failed", "reason": repair_reason[:1200]})
      persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key=f"artifact_error_{len(state['repair_errors'])}", kind="error", content=repair_reason[:2400], project_id=project_id)
      raise AgentRuntimeLoopError(repair_reason) from exc
  changed_candidate_files = artifact_files_to_tool_files(generated_website["files"])
  candidate_files = merge_candidate_files_for_operation(
    operation=text_or_default(state.get("operation"), "generate"),
    read_result=object_value(state.get("read_result")),
    changed_files=changed_candidate_files,
  )
  changed_file_paths = [file_item["path"] for file_item in changed_candidate_files]
  if text_or_default(state.get("operation"), "generate") == "update":
    generated_website = {
      **generated_website,
      "files": tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_file_paths),
    }
  state["artifact_response"] = artifact_response
  if isinstance(artifact_response, dict) and isinstance(artifact_response.get("_context_budget"), dict):
    state["token_budget_used"] = artifact_response["_context_budget"]
  state["generated_website"] = generated_website
  state["files"] = generated_website["files"]
  state["candidate_files"] = candidate_files
  state["changed_file_paths"] = changed_file_paths
  state["validation_result"] = None
  state["preview_result"] = None
  state["preview"] = None
  state["visual_qa_result"] = None
  state["committed"] = False
  state["files_materialized"] = False
  state["materialized_file_paths"] = []
  state["materialized_file_signatures"] = {}
  state["dynamic_patch_integrated"] = action == "RUN_REPAIR_AGENT" or not list_value(state.get("candidate_changes"))
  if action == "RUN_REPAIR_AGENT" and list_value(state.get("candidate_changes")):
    summary = object_value(state.get("candidate_change_summary"))
    summary["integration_status"] = "rejected_after_repair_trigger"
    summary["integration_reason"] = previous_error
    state["candidate_change_summary"] = summary
  state["repair_errors"] = []
  append_step(
    state,
    agent,
    "repair_project_artifact"
    if action == "RUN_REPAIR_AGENT"
    else "generate_update_artifact"
    if text_or_default(state.get("operation"), "generate") == "update"
    else "generate_project_artifact",
    {"plan": object_value(state.get("plan")), "previous_error": previous_error},
    {
      "title": generated_website["title"],
      "section_count": len(generated_website["sections"]),
      "file_count": len(generated_website["files"]),
      "changed_file_paths": list(state.get("changed_file_paths") or []),
      "paths": [file_item["path"] for file_item in generated_website["files"]],
      "artifact_fallback": state.get("artifact_fallback"),
    },
  )
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="repair_candidate_prepared" if action == "RUN_REPAIR_AGENT" else "code_candidate_prepared",
    message_prefix="Prepared repaired code changes" if action == "RUN_REPAIR_AGENT" else "Prepared generated code changes",
  )
  return
