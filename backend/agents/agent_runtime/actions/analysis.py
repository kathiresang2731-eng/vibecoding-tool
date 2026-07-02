from __future__ import annotations

try:
  from ....audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..error_handling import analyze_error_context
from ..file_ops import project_files_to_tool_files
from ..memory import persist_memory_checkpoint
from ..model_agents import run_planner_agent, run_prompt_analyst_agent, run_review_agent
from ...prompt_context import current_user_prompt
from ..progress import emit_candidate_code_diff_progress, emit_runtime_progress, website_plan_progress_detail
from ..state import append_step, record_agent_message, refresh_conversation_requirement
from ..targeted_runtime import apply_targeted_update_shortcut
from ..update_analysis import build_update_code_search_matches, run_update_analysis_agent
from ..values import list_value, object_value, text_or_default
from .context import RuntimeActionContext


def handle_error_handling_agent(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  current_prompt = current_user_prompt(state["prompt"])
  existing_files = project_files_to_tool_files(object_value(state.get("read_result")).get("files"))
  code_search_matches = build_update_code_search_matches(current_prompt, existing_files)
  error_diagnosis = analyze_error_context(
    current_prompt,
    existing_files=existing_files,
    code_search_matches=code_search_matches,
  )
  state["error_diagnosis"] = error_diagnosis
  state["update_code_search_matches"] = code_search_matches
  ctx.prepared_sections["error_diagnosis"] = error_diagnosis
  append_step(
    state,
    ctx.agent,
    "diagnose_user_provided_error",
    {"prompt": current_prompt, "existing_file_count": len(existing_files)},
    error_diagnosis,
  )
  emit_runtime_progress(
    ctx.progress,
    "error.diagnosed",
    "Error handling agent diagnosed the runtime failure and selected likely files",
    status="completed",
    detail=error_diagnosis,
  )


def update_request_summary_progress_detail(update_analysis: dict[str, object]) -> dict[str, object]:
  tasks = [
    task
    for task in list_value(update_analysis.get("scoped_update_tasks"))
    if isinstance(task, dict)
  ]
  return {
    "summary": text_or_default(update_analysis.get("summary"), "Apply the requested website update."),
    "update_mode": update_analysis.get("update_mode"),
    "request_kind": update_analysis.get("request_kind"),
    "execution_strategy": update_analysis.get("execution_strategy"),
    "scope": update_analysis.get("scope"),
    "decision_reason": text_or_default(update_analysis.get("reason"), ""),
    "selected_agent": "Targeted Update Agent" if update_analysis.get("execution_strategy") == "deterministic_patch" else "Scoped Update Agent",
    "selected_action": "APPLY_TARGETED_UPDATE_SHORTCUT" if update_analysis.get("execution_strategy") == "deterministic_patch" else "RUN_SCOPED_UPDATE_AGENT",
    "candidate_files": update_analysis.get("candidate_files"),
    "candidate_new_files": update_analysis.get("candidate_new_files"),
    "task_count": len(tasks),
    "tasks": [
      {
        "id": text_or_default(task.get("id"), f"task_{index + 1}"),
        "summary": text_or_default(task.get("summary"), text_or_default(task.get("prompt"), "")),
        "candidate_files": list_value(task.get("candidate_files")),
        "candidate_new_files": list_value(task.get("candidate_new_files")),
      }
      for index, task in enumerate(tasks[:6])
    ],
  }


def update_request_summary_message(update_analysis: dict[str, object]) -> str:
  summary = text_or_default(update_analysis.get("summary"), "I understood the requested website update.")
  candidate_files = [
    str(path)
    for path in list_value(update_analysis.get("candidate_files"))
    if str(path).strip()
  ]
  task_count = len([
    task
    for task in list_value(update_analysis.get("scoped_update_tasks"))
    if isinstance(task, dict)
  ])
  file_text = f" Focused files: {', '.join(candidate_files[:3])}." if candidate_files else ""
  task_text = f" I split it into {task_count} {('task' if task_count == 1 else 'tasks')}." if task_count else ""
  return f"I understood the update: {summary}.{task_text}{file_text}"


def handle_update_analyst(ctx: RuntimeActionContext) -> None:
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

  current_prompt = current_user_prompt(state["prompt"])
  existing_files = project_files_to_tool_files(object_value(state.get("read_result")).get("files"))
  code_search_matches = list_value(state.get("update_code_search_matches")) or build_update_code_search_matches(current_prompt, existing_files)
  update_analysis = run_update_analysis_agent(
    control_provider,
    current_prompt,
    object_value(state.get("read_result")),
    object_value(state.get("memory_result")),
    code_search_matches=code_search_matches,
    error_diagnosis=object_value(state.get("error_diagnosis")),
  )
  state["update_analysis"] = update_analysis
  state["update_code_search_matches"] = code_search_matches
  requirement_trace = refresh_conversation_requirement(
    state,
    update_analysis=update_analysis,
    selected_files=[
      str(path)
      for path in list_value(update_analysis.get("candidate_files"))
      if str(path).strip()
    ],
  )
  prepared_sections["update_analysis"] = update_analysis
  prepared_sections["conversation_requirement"] = requirement_trace
  append_step(
    state,
    agent,
    "analyze_update_scope",
    {"prompt": current_prompt, "existing_file_count": len(existing_files)},
    update_analysis,
  )
  log_query_event(
    "update_analysis.completed",
    payload={
      "update_mode": update_analysis.get("update_mode"),
      "request_kind": update_analysis.get("request_kind"),
      "execution_strategy": update_analysis.get("execution_strategy"),
      "scope": update_analysis.get("scope"),
      "feature_plan": update_analysis.get("feature_plan"),
      "candidate_files": update_analysis.get("candidate_files"),
      "candidate_new_files": update_analysis.get("candidate_new_files"),
      "new_file_requirements": update_analysis.get("new_file_requirements"),
      "scoped_update_tasks": update_analysis.get("scoped_update_tasks"),
      "required_agents": update_analysis.get("required_agents"),
      "targeted_patch": update_analysis.get("targeted_patch"),
      "allow_full_regeneration": update_analysis.get("allow_full_regeneration"),
      "requirement_trace": requirement_trace,
    },
  )
  emit_runtime_progress(
    progress,
    "update.summary",
    update_request_summary_message(update_analysis),
    status="completed",
    detail=update_request_summary_progress_detail(update_analysis),
  )
  update_mode = text_or_default(update_analysis.get("update_mode"), "needs_clarification")
  if update_mode == "needs_clarification":
    raise UpdateRequestNeedsClarificationError(
      "Update request needs clarification before editing files: "
      + text_or_default(
        update_analysis.get("clarification_question"),
        "Please describe the exact existing behavior or component to change.",
      )
    )
  if update_mode == "full_regeneration" and not update_analysis.get("allow_full_regeneration"):
    raise ScopedUpdateGuardError(
      "The update analysis requested full regeneration without explicit user approval. "
      "The existing website was preserved."
    )
  if update_analysis.get("execution_strategy") == "deterministic_patch":
    if not apply_targeted_update_shortcut(state, project_id=project_id):
      raise ScopedUpdateGuardError(
        "The model selected a targeted patch, but Python could not safely apply it. "
        "The existing website was preserved."
      )
    prepared_sections["targeted_update"] = state.get("targeted_update")
    append_step(
      state,
      "Targeted Update Agent",
      "apply_model_selected_targeted_update",
      {"prompt": current_prompt, "update_analysis": update_analysis},
      object_value(state.get("targeted_update")),
    )
    emit_runtime_progress(
      progress,
      "plan.created",
      "Targeted update plan is ready",
      status="completed",
      detail=website_plan_progress_detail(object_value(state.get("plan")), object_value(state.get("dynamic_workflow_plan"))),
    )
    emit_candidate_code_diff_progress(
      state,
      progress,
      stage="targeted_update_prepared",
      message_prefix="Prepared targeted code changes",
    )
    record_agent_message(
      state,
      from_agent="Targeted Update Agent",
      to_agent="Supervisor Agent",
      content="Applied the model-selected targeted patch to existing project files.",
      action="APPLY_MODEL_SELECTED_TARGETED_UPDATE",
    )
  return

def handle_prompt_analyst(ctx: RuntimeActionContext) -> None:
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

  brief = run_prompt_analyst_agent(control_provider, state["prompt"], state["routing_result"], object_value(state.get("read_result")), object_value(state.get("memory_result")))
  domain_research = object_value(brief.get("domain_research"))
  state["brief"] = brief
  state["domain_research"] = domain_research
  prepared_sections["domain_research"] = domain_research
  append_step(
    state,
    agent,
    "create_structured_brief",
    {"prompt": state["prompt"], "routing_result": state["routing_result"], "existing_file_count": object_value(state.get("read_result")).get("file_count", 0)},
    brief,
  )
  persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key="latest_brief", kind="brief", content=brief, project_id=project_id)
  return

def handle_planner(ctx: RuntimeActionContext) -> None:
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

  plan = run_planner_agent(control_provider, state["prompt"], object_value(state.get("brief")), prepared_sections, object_value(state.get("memory_result")))
  state["plan"] = plan
  append_step(state, agent, "create_website_plan", {"brief": object_value(state.get("brief"))}, plan)
  emit_runtime_progress(
    progress,
    "plan.created",
    "Website implementation plan is ready",
    status="completed",
    detail=website_plan_progress_detail(plan, object_value(state.get("dynamic_workflow_plan"))),
  )
  persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key="latest_plan", kind="plan", content=plan, project_id=project_id)
  return

def handle_ux_review(ctx: RuntimeActionContext) -> None:
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

  review = run_review_agent(
    control_provider,
    trace_label="ux_review_agent",
    system_instruction="You are a UX review agent. Return strict JSON only.",
    prompt="Review the website plan for user workflow, conversion clarity, responsive layout, and missing content.",
    state=state,
  )
  state["ux_review"] = review
  append_step(state, agent, "review_ux_plan", {"plan": object_value(state.get("plan"))}, review)
  persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key="latest_ux_review", kind="review", content=review, project_id=project_id)
  return

def handle_accessibility_review(ctx: RuntimeActionContext) -> None:
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

  review = run_review_agent(
    control_provider,
    trace_label="accessibility_review_agent",
    system_instruction="You are an accessibility review agent. Return strict JSON only.",
    prompt="Review the website plan for color contrast, semantic structure, keyboard flow, and mobile text fit.",
    state=state,
  )
  state["accessibility_review"] = review
  append_step(state, agent, "review_accessibility_plan", {"plan": object_value(state.get("plan"))}, review)
  persist_memory_checkpoint(state, tool_context=tool_context, user=user, namespace="agent", key="latest_accessibility_review", kind="review", content=review, project_id=project_id)
  return


def handle_parallel_review_agents(ctx: RuntimeActionContext) -> None:
  from ..parallel_actions import run_parallel_review_agents

  state = ctx.state
  parallel_result = run_parallel_review_agents(ctx.control_provider, state=state)
  ux_review = object_value(parallel_result.get("ux_review"))
  accessibility_review = object_value(parallel_result.get("accessibility_review"))
  state["ux_review"] = ux_review
  state["accessibility_review"] = accessibility_review
  append_step(
    state,
    ctx.agent,
    "parallel_review_agents",
    {"plan": object_value(state.get("plan"))},
    {
      "parallel_execution_engine": parallel_result.get("parallel_execution_engine"),
      "ux_status": ux_review.get("status"),
      "accessibility_status": accessibility_review.get("status"),
    },
  )
  append_step(state, "UX Review Agent", "review_ux_plan", {"plan": object_value(state.get("plan"))}, ux_review)
  append_step(
    state,
    "Accessibility Agent",
    "review_accessibility_plan",
    {"plan": object_value(state.get("plan"))},
    accessibility_review,
  )
  persist_memory_checkpoint(
    state,
    tool_context=ctx.tool_context,
    user=ctx.user,
    namespace="agent",
    key="latest_ux_review",
    kind="review",
    content=ux_review,
    project_id=ctx.project_id,
  )
  persist_memory_checkpoint(
    state,
    tool_context=ctx.tool_context,
    user=ctx.user,
    namespace="agent",
    key="latest_accessibility_review",
    kind="review",
    content=accessibility_review,
    project_id=ctx.project_id,
  )
