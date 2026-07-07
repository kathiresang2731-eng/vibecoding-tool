from __future__ import annotations

from typing import Any, Callable

try:
  from ....agent_tools import ToolRuntimeContext
  from ...mas import assert_mas_action_allowed, begin_mas_action, complete_mas_action, fail_mas_action, MASContractError
except ImportError:
  from agent_tools import ToolRuntimeContext
  from agents.mas import assert_mas_action_allowed, begin_mas_action, complete_mas_action, fail_mas_action, MASContractError

from ..errors import AgentRuntimeLoopError
from ..state import record_agent_message
from .context import RuntimeActionContext, ToolExecutor
from ...runtime_agents.agent_registry_agent.handlers import handle_dynamic_agent_planner, handle_dynamic_specialists
from ...runtime_agents.code_agent.handlers import (
  handle_code_or_repair_agent,
)
from ...runtime_agents.code_generator_agent.handlers import handle_dynamic_patch_integrator
from ...runtime_agents.commit_agent.handlers import handle_write_project_files
from ...runtime_agents.error_handling_agent.handlers import handle_error_handling_agent
from ...runtime_agents.memory_agent.handlers import (
  handle_load_project_memory,
  handle_parallel_project_bootstrap,
  handle_persist_project_memory,
  handle_read_project_files,
)
from ...runtime_agents.materialize_agent.handlers import handle_materialize_candidate_files
from ...runtime_agents.planner_agent.handlers import handle_planner
from ...runtime_agents.preview_agent.handlers import handle_build_staged_project_preview
from ...runtime_agents.prompt_analyst_agent.handlers import handle_prompt_analyst
from ...runtime_agents.repair_agent.handlers import handle_code_or_repair_agent as handle_repair_agent
from ...runtime_agents.review_agents.handlers import handle_accessibility_review, handle_parallel_review_agents, handle_ux_review
from ...runtime_agents.scoped_update_agent.handlers import handle_scoped_update_agent
from ...runtime_agents.update_analysis_agent.handlers import handle_update_analyst
from ...runtime_agents.validation_agent.handlers import handle_validate_project_artifact
from ...runtime_agents.visual_qa_agent.handlers import handle_run_preview_visual_qa


AgentProgressCallback = Callable[..., None]


def execute_loop_action(
  action: str,
  *,
  state: dict[str, Any],
  decision: dict[str, Any],
  control_provider: Any,
  artifact_provider: Any,
  prepared_sections: dict[str, Any],
  tool_executor: ToolExecutor,
  tool_context: ToolRuntimeContext,
  user: Any,
  project_id: str,
  start_time: float,
  timeout_seconds: int,
  progress: AgentProgressCallback,
  runtime_objects: dict[str, Any] | None = None,
) -> None:
  ctx = RuntimeActionContext(
    action=action,
    state=state,
    decision=decision,
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    prepared_sections=prepared_sections,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    start_time=start_time,
    timeout_seconds=timeout_seconds,
    progress=progress,
    runtime_objects=runtime_objects or {},
  )
  try:
    assert_mas_action_allowed(state, action)
  except MASContractError as exc:
    raise AgentRuntimeLoopError(str(exc)) from exc

  before_step_count = len(state.get("agent_steps") or [])
  before_tool_call_count = len(state.get("tool_calls") or [])
  begin_mas_action(state, action=action, agent=ctx.agent, decision=decision)
  state["action_history"].append(action)
  record_agent_message(
    state,
    from_agent="Supervisor Agent",
    to_agent=ctx.agent,
    content=decision["reason"],
    action=action,
  )

  handler = ACTION_HANDLERS.get(action)
  if handler is None:
    raise AgentRuntimeLoopError(f"Unsupported runtime action: {action}")
  try:
    handler(ctx)
  except Exception as exc:
    fail_mas_action(
      state,
      action=action,
      agent=ctx.agent,
      error=exc,
      before_step_count=before_step_count,
      before_tool_call_count=before_tool_call_count,
    )
    raise
  complete_mas_action(
    state,
    action=action,
    agent=ctx.agent,
    before_step_count=before_step_count,
    before_tool_call_count=before_tool_call_count,
  )


ACTION_HANDLERS: dict[str, Callable[[RuntimeActionContext], None]] = {
  "READ_PROJECT_FILES": handle_read_project_files,
  "LOAD_PROJECT_MEMORY": handle_load_project_memory,
  "RUN_PARALLEL_PROJECT_BOOTSTRAP": handle_parallel_project_bootstrap,
  "RUN_UPDATE_ANALYST": handle_update_analyst,
  "RUN_ERROR_HANDLING_AGENT": handle_error_handling_agent,
  "RUN_SCOPED_UPDATE_AGENT": handle_scoped_update_agent,
  "RUN_PROMPT_ANALYST": handle_prompt_analyst,
  "RUN_DYNAMIC_AGENT_PLANNER": handle_dynamic_agent_planner,
  "RUN_PLANNER": handle_planner,
  "RUN_DYNAMIC_SPECIALISTS": handle_dynamic_specialists,
  "RUN_UX_REVIEW_AGENT": handle_ux_review,
  "RUN_ACCESSIBILITY_AGENT": handle_accessibility_review,
  "RUN_PARALLEL_REVIEW_AGENTS": handle_parallel_review_agents,
  "RUN_CODE_AGENT": handle_code_or_repair_agent,
  "RUN_REPAIR_AGENT": handle_repair_agent,
  "RUN_DYNAMIC_PATCH_INTEGRATOR": handle_dynamic_patch_integrator,
  "MATERIALIZE_CANDIDATE_FILES": handle_materialize_candidate_files,
  "VALIDATE_PROJECT_ARTIFACT": handle_validate_project_artifact,
  "BUILD_STAGED_PROJECT_PREVIEW": handle_build_staged_project_preview,
  "RUN_PREVIEW_VISUAL_QA": handle_run_preview_visual_qa,
  "WRITE_PROJECT_FILES": handle_write_project_files,
  "PERSIST_PROJECT_MEMORY": handle_persist_project_memory,
}
