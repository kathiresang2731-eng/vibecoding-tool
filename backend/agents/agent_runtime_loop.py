from __future__ import annotations

import time
from typing import Any, Callable

try:
  from ..agent_tools import ToolRuntimeContext, execute_codex_tool
  from ..debug_trace import trace_function
except ImportError:
  from agent_tools import ToolRuntimeContext, execute_codex_tool
  from debug_trace import trace_function

from .agent_runtime.errors import AgentRuntimeLoopError
from .agent_runtime.loop_core import RuntimeLoopParams, prepare_runtime_loop_state, run_legacy_runtime_loop
from .agent_runtime.supervision import effective_repair_attempt_budget
from .agent_runtime.timeouts import runtime_timeout_seconds
from .providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, assert_provider_role
from .runtime_config import runtime_engine


AgentProgressCallback = Callable[..., None]
ToolExecutor = Callable[[str, ToolRuntimeContext, Any, dict[str, Any]], dict[str, Any]]


def _build_loop_params(
  *,
  project_id: str,
  user: Any,
  tool_context: ToolRuntimeContext,
  prompt: str,
  routing_result: dict[str, Any],
  control_provider: Any,
  artifact_provider: Any,
  prepared_sections: dict[str, Any],
  emit_progress: Callable[..., None] | None,
  tool_executor: ToolExecutor,
  max_repair_attempts: int,
  max_steps: int,
  max_tool_calls: int,
  timeout_seconds: int,
  agent_run_id: str | None = None,
  graph_thread_id: str | None = None,
  resume_graph: bool = False,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
) -> RuntimeLoopParams:
  progress = emit_progress or (lambda _step, _message, **_kwargs: None)
  return RuntimeLoopParams(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    routing_result=routing_result,
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    prepared_sections=prepared_sections,
    progress=progress,
    tool_executor=tool_executor,
    repair_attempt_budget=effective_repair_attempt_budget(max_repair_attempts),
    max_steps=max_steps,
    max_tool_calls=max_tool_calls,
    timeout_seconds=timeout_seconds,
    start_time=time.monotonic(),
    agent_run_id=agent_run_id,
    graph_thread_id=graph_thread_id,
    resume_graph=resume_graph,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    patch_action=patch_action if patch_action in {"approve", "reject"} else None,
    runtime_objects={},
  )


@trace_function(project_id=lambda **kwargs: kwargs.get("project_id"), intent=lambda **kwargs: (kwargs.get("routing_result") or {}).get("intent"))
def execute_agent_runtime_loop(
  *,
  project_id: str,
  user: Any,
  tool_context: ToolRuntimeContext,
  prompt: str,
  routing_result: dict[str, Any],
  control_provider: Any,
  artifact_provider: Any,
  prepared_sections: dict[str, Any],
  emit_progress: Callable[..., None] | None = None,
  tool_executor: ToolExecutor = execute_codex_tool,
  max_repair_attempts: int = 1,
  max_steps: int = 28,
  max_tool_calls: int = 36,
  timeout_seconds: int | None = None,
  agent_run_id: str | None = None,
  graph_thread_id: str | None = None,
  resume_graph: bool = False,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
) -> dict[str, Any]:
  assert_provider_role(control_provider, CONTROL_PROVIDER_ROLE)
  assert_provider_role(artifact_provider, ARTIFACT_PROVIDER_ROLE)
  timeout_seconds = runtime_timeout_seconds() if timeout_seconds is None else timeout_seconds
  params = _build_loop_params(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    routing_result=routing_result,
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    prepared_sections=prepared_sections,
    emit_progress=emit_progress,
    tool_executor=tool_executor,
    max_repair_attempts=max_repair_attempts,
    max_steps=max_steps,
    max_tool_calls=max_tool_calls,
    timeout_seconds=timeout_seconds,
    agent_run_id=agent_run_id,
    graph_thread_id=graph_thread_id,
    resume_graph=resume_graph,
    chat_session_id=chat_session_id,
    chat_topic_id=chat_topic_id,
    project_name=project_name,
    patch_action=patch_action if patch_action in {"approve", "reject"} else None,
  )
  if runtime_engine() == "langgraph":
    from .graph_runtime.loop import execute_langgraph_agent_runtime_loop

    return execute_langgraph_agent_runtime_loop(params)
  state = prepare_runtime_loop_state(params)
  return run_legacy_runtime_loop(params, state)


def execute_real_agent_runtime_loop(**kwargs: Any) -> dict[str, Any]:
  return execute_agent_runtime_loop(**kwargs)


# Backward-compatible re-exports for tests and legacy imports.
from .agent_runtime.errors import ScopedUpdateGuardError  # noqa: E402
from .agent_runtime.fallbacks import is_artifact_json_invalid_error, should_use_deterministic_artifact_fallback  # noqa: E402
from .agent_runtime.memory import build_project_state_memory  # noqa: E402
from .agent_runtime.model_agents import (  # noqa: E402
  run_artifact_provider_with_soft_timeout,
  run_code_agent,
  run_planner_agent,
  run_prompt_analyst_agent,
)
from .agent_runtime.progress import emit_candidate_code_diff_progress, enforce_loop_budget  # noqa: E402
from .agent_runtime.scaffolding import ensure_tailwind_runtime_files, ensure_vite_scaffold_files  # noqa: E402
from .agent_runtime.scoped_update import validate_scoped_update_changes  # noqa: E402
from .agent_runtime.scoped_update.runtime import run_scoped_update_agent  # noqa: E402
from .agent_runtime.timeouts import (  # noqa: E402
  artifact_call_soft_timeout_seconds,
  artifact_model_soft_timeout_seconds,
  repair_model_soft_timeout_seconds,
  runtime_timeout_seconds,
  scoped_update_model_soft_timeout_seconds,
  scoped_update_sequence_timeout_seconds,
)
from .agent_runtime.update_analysis import build_update_code_search_matches, normalize_update_analysis  # noqa: E402

__all__ = [
  "AgentRuntimeLoopError",
  "ScopedUpdateGuardError",
  "artifact_call_soft_timeout_seconds",
  "artifact_model_soft_timeout_seconds",
  "build_project_state_memory",
  "build_update_code_search_matches",
  "enforce_loop_budget",
  "ensure_tailwind_runtime_files",
  "ensure_vite_scaffold_files",
  "emit_candidate_code_diff_progress",
  "execute_agent_runtime_loop",
  "execute_real_agent_runtime_loop",
  "is_artifact_json_invalid_error",
  "repair_model_soft_timeout_seconds",
  "runtime_timeout_seconds",
  "scoped_update_model_soft_timeout_seconds",
  "scoped_update_sequence_timeout_seconds",
  "run_scoped_update_agent",
  "run_planner_agent",
  "run_prompt_analyst_agent",
  "run_code_agent",
  "run_artifact_provider_with_soft_timeout",
  "should_use_deterministic_artifact_fallback",
  "normalize_update_analysis",
  "validate_scoped_update_changes",
]
