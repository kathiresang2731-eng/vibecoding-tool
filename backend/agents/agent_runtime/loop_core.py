from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

try:
  from ...agent_tools import ToolRuntimeContext, execute_website_tool, website_tool_schemas
  from ...audit_logging import log_query_event
  from ...debug_trace import trace_print
except ImportError:
  from agent_tools import ToolRuntimeContext, execute_website_tool, website_tool_schemas
  from audit_logging import log_query_event
  from debug_trace import trace_function, trace_print

from ..runtime_config import agentic_parity_target, runtime_engine
from .actions import execute_loop_action
from .constants import SUPERVISOR_GOAL
from .errors import AgentRuntimeLoopError, TargetedUpdateNoMatchError
from .fallbacks import is_retriable_scoped_update_guard_error, should_abort_runtime_without_repair
from .progress import (
  action_progress_detail,
  action_progress_message,
  completion_proof,
  completion_status,
  emit_runtime_progress,
  enforce_loop_budget,
)
from .repair_tracking import record_repair_error
from .runtime_summary import build_runtime_summary, promote_dynamic_agents
from .state import append_step, initial_runtime_state
from .supervision import (
  available_runtime_actions,
  effective_repair_attempt_budget,
  is_scoped_update_mode,
  mark_supervisor_audit_completion_rejected,
  supervisor_choose_next_action,
)
from .timeouts import runtime_timeout_seconds
from .tooling import restore_previous_project_files
from .values import object_value

try:
  from ..patch_approval import finalize_awaiting_patch_approval_result
except ImportError:
  from patch_approval import finalize_awaiting_patch_approval_result

try:
  from ..schema.json_safe import scrub_runtime_objects_from_state
except ImportError:
  from schema.json_safe import scrub_runtime_objects_from_state


AgentProgressCallback = Callable[..., None]
ToolExecutor = Callable[[str, ToolRuntimeContext, Any, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RuntimeLoopParams:
  project_id: str
  user: Any
  tool_context: ToolRuntimeContext
  prompt: str
  routing_result: dict[str, Any]
  control_provider: Any
  artifact_provider: Any
  prepared_sections: dict[str, Any]
  progress: AgentProgressCallback
  tool_executor: ToolExecutor
  repair_attempt_budget: int
  max_steps: int
  max_tool_calls: int
  timeout_seconds: int
  start_time: float
  agent_run_id: str | None = None
  graph_thread_id: str | None = None
  resume_graph: bool = False
  chat_session_id: str | None = None
  project_name: str = ""
  patch_action: str | None = None
  runtime_objects: dict[str, Any] = field(default_factory=dict)


def prepare_runtime_loop_state(params: RuntimeLoopParams) -> dict[str, Any]:
  state = initial_runtime_state(
    project_id=params.project_id,
    prompt=params.prompt,
    routing_result=params.routing_result,
  )
  state["chat_session_id"] = params.chat_session_id
  state["agent_run_id"] = params.agent_run_id
  state["project_name"] = params.project_name
  state["patch_action"] = params.patch_action if params.patch_action in {"approve", "reject"} else None
  state["runtime_engine"] = runtime_engine()
  state["agentic_parity_target"] = agentic_parity_target()
  append_step(
    state,
    "Intent Router Agent",
    "route_user_turn",
    {"prompt": params.prompt},
    params.routing_result,
  )
  return state


def run_supervisor_decision(state: dict[str, Any], params: RuntimeLoopParams) -> tuple[dict[str, Any], dict[str, Any], str | None]:
  enforce_loop_budget(
    state,
    start_time=params.start_time,
    timeout_seconds=params.timeout_seconds,
    max_tool_calls=params.max_tool_calls,
  )
  available_actions = available_runtime_actions(state, max_repair_attempts=params.repair_attempt_budget)
  if not available_actions:
    restore_previous_project_files(
      state,
      tool_executor=params.tool_executor,
      tool_context=params.tool_context,
      user=params.user,
      project_id=params.project_id,
      read_result=object_value(state.get("read_result")),
    )
    raise AgentRuntimeLoopError("Agent runtime has no legal next action; restored previous project files.")

  decision = supervisor_choose_next_action(
    state,
    supervisor_provider=params.control_provider,
    goal=SUPERVISOR_GOAL,
    available_actions=available_actions,
    available_tools=website_tool_schemas(),
  )
  action = decision["next_action"]
  trace_print(
    "EXIT",
    file=__file__,
    class_name="RuntimeLoopCore",
    function="supervisor_choose_next_action",
    action=action,
    agent=decision.get("next_agent"),
    step_count=len(state.get("steps") or []),
  )
  if action == "DONE":
    if not completion_proof(state):
      rejection = {
        "audit_id": decision.get("audit_id"),
        "requested_action": "DONE",
        "reason": "Supervisor requested DONE before completion proof was satisfied.",
        "completion_status": completion_status(state),
      }
      state["supervisor_completion_rejections"].append(rejection)
      mark_supervisor_audit_completion_rejected(state, rejection)
      state["supervisor_policy_fallbacks"].append(
        {
          "audit_id": decision.get("audit_id"),
          "model_output": decision.get("model_output"),
          "fallback_reason": rejection["reason"],
        }
      )
      return state, decision, None
    promote_dynamic_agents(state, tool_context=params.tool_context, user=params.user, runtime_objects=params.runtime_objects)
    state["completed"] = True
    append_step(state, "Supervisor Agent", "done", {"completion_proof": completion_status(state)}, {"status": "completed"})
    scrub_runtime_objects_from_state(state)
    return state, decision, "DONE"

  state["_pending_decision"] = decision
  state["_pending_action"] = action
  scrub_runtime_objects_from_state(state)
  return state, decision, None


def run_action_for_decision(state: dict[str, Any], params: RuntimeLoopParams, *, action: str) -> dict[str, Any]:
  decision = object_value(state.get("_pending_decision"))
  if not decision:
    raise AgentRuntimeLoopError(f"Missing supervisor decision before executing action {action}.")
  if str(decision.get("next_action") or "") != action:
    raise AgentRuntimeLoopError(
      f"Graph action mismatch: node={action}, supervisor={decision.get('next_action')}."
    )

  progress_message = action_progress_message(action, decision, state)
  emit_runtime_progress(
    params.progress,
    f"agent.loop.{action.lower()}",
    progress_message,
    detail=action_progress_detail(action, state, decision),
  )
  try:
    execute_loop_action(
      action,
      state=state,
      decision=decision,
      control_provider=params.control_provider,
      artifact_provider=params.artifact_provider,
      prepared_sections=params.prepared_sections,
      tool_executor=params.tool_executor,
      tool_context=params.tool_context,
      user=params.user,
      project_id=params.project_id,
      start_time=params.start_time,
      timeout_seconds=params.timeout_seconds,
      progress=params.progress,
      runtime_objects=params.runtime_objects,
    )
  except TargetedUpdateNoMatchError as exc:
    if (
      is_scoped_update_mode(state)
      and is_retriable_scoped_update_guard_error(exc)
      and state["repair_attempts"] < params.repair_attempt_budget
    ):
      record_repair_error(state, str(exc), source="scoped_update_guard")
      log_query_event(
        "scoped_update.retry_scheduled",
        payload={
          "reason": str(exc)[:1200],
          "repair_attempt": int(state.get("repair_attempts") or 0) + 1,
        },
      )
      return state
    raise
  except AgentRuntimeLoopError as exc:
    if should_abort_runtime_without_repair(exc):
      raise
    record_repair_error(state, str(exc), source="agent_runtime_error")
    if state["repair_attempts"] >= params.repair_attempt_budget:
      restore_previous_project_files(
        state,
        tool_executor=params.tool_executor,
        tool_context=params.tool_context,
        user=params.user,
        project_id=params.project_id,
        read_result=object_value(state.get("read_result")),
      )
      raise AgentRuntimeLoopError(
        f"Agent loop failed after repair budget; restored previous project files: {str(exc)[:1200]}"
      ) from exc
    return state
  finally:
    state.pop("_pending_decision", None)
    state.pop("_pending_action", None)
  scrub_runtime_objects_from_state(state)
  return state


def run_runtime_loop_iteration(state: dict[str, Any], params: RuntimeLoopParams) -> tuple[dict[str, Any], str | None]:
  state, decision, terminal_action = run_supervisor_decision(state, params)
  if terminal_action == "DONE":
    return state, "DONE"
  action = str(decision.get("next_action") or "")
  if not action or action == "DONE":
    return state, None
  return run_action_for_decision(state, params, action=action), None


def finalize_runtime_loop_result(state: dict[str, Any], *, last_action: str | None = None) -> dict[str, Any]:
  if state.get("awaiting_patch_approval"):
    generated_website = object_value(state.get("generated_website"))
    if not generated_website:
      candidate_files = [
        {"path": str(item.get("path") or ""), "content": str(item.get("content") or item.get("code") or "")}
        for item in list(state.get("candidate_files") or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
      ]
      generated_website = {
        "title": "Proposed patch",
        "subheadline": str(state.get("prompt") or ""),
        "files": candidate_files,
      }
    runtime = build_runtime_summary(state, generated_website, state.get("validation_result"), state.get("preview_result"))
    return finalize_awaiting_patch_approval_result(state, generated_website=generated_website, runtime=runtime)

  if not state.get("completed"):
    raise AgentRuntimeLoopError("Agent runtime exhausted its step budget before DONE; restored previous project files.")

  generated_website = object_value(state.get("generated_website"))
  artifact_response = object_value(state.get("artifact_response"))
  runtime = build_runtime_summary(state, generated_website, state.get("validation_result"), state.get("preview_result"))
  return {
    "state": state,
    "artifact_response": artifact_response,
    "generated_website": generated_website,
    "runtime": runtime,
    "local_sync": state.get("local_sync"),
    "preview": state.get("preview"),
  }


def run_legacy_runtime_loop(params: RuntimeLoopParams, state: dict[str, Any]) -> dict[str, Any]:
  last_action: str | None = None
  for _loop_index in range(params.max_steps):
    state, terminal_action = run_runtime_loop_iteration(state, params)
    if state.get("awaiting_patch_approval"):
      return finalize_runtime_loop_result(state)
    if terminal_action == "DONE":
      break
    last_action = terminal_action
  if state.get("awaiting_patch_approval"):
    return finalize_runtime_loop_result(state)
  if not state.get("completed"):
    restore_previous_project_files(
      state,
      tool_executor=params.tool_executor,
      tool_context=params.tool_context,
      user=params.user,
      project_id=params.project_id,
      read_result=object_value(state.get("read_result")),
    )
    trace_print(
      "EXIT",
      file=__file__,
      class_name="RuntimeLoopCore",
      function="run_legacy_runtime_loop",
      action=last_action,
      changed_files=len(state.get("changed_file_paths") or []),
      tool_calls=len(state.get("tool_calls") or []),
    )
    raise AgentRuntimeLoopError("Agent runtime exhausted its step budget before DONE; restored previous project files.")
  return finalize_runtime_loop_result(state, last_action=last_action)
