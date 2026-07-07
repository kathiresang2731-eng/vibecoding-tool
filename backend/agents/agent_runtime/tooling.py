from __future__ import annotations

from typing import Any, Callable

try:
  from ...agent_tools import ToolRuntimeContext
  from ...audit_logging import log_query_event
except ImportError:
  from agent_tools import ToolRuntimeContext
  from audit_logging import log_query_event

from ..artifacts import validate_project_artifact
from .errors import AgentRuntimeLoopError
from .file_ops import project_files_to_tool_files
from .state import append_step


ToolExecutor = Callable[[str, ToolRuntimeContext, Any, dict[str, Any]], dict[str, Any]]


def execute_tool_call(
  state: dict[str, Any],
  *,
  tool_executor: ToolExecutor,
  tool_context: ToolRuntimeContext,
  user: Any,
  agent: str,
  name: str,
  arguments: dict[str, Any],
) -> dict[str, Any]:
  call_id = f"{len(state['tool_calls']) + 1:03d}-{name.lower()}"
  log_query_event(
    "tool.requested",
    status="running",
    payload={"call_id": call_id, "tool_name": name, "agent": agent, "arguments": arguments},
  )
  try:
    result = tool_executor(name, tool_context, user, arguments)
  except Exception as exc:
    state["tool_calls"].append(
      {
        "call_id": call_id,
        "name": name,
        "agent": agent,
        "arguments": arguments,
        "status": "failed",
        "error": str(exc),
      }
    )
    log_query_event(
      "tool.failed",
      status="failed",
      payload={"call_id": call_id, "tool_name": name, "agent": agent, "arguments": arguments, "error": str(exc)},
    )
    raise AgentRuntimeLoopError(f"{agent} tool {name} failed: {exc}") from exc
  state["tool_calls"].append(
    {
      "call_id": call_id,
      "name": name,
      "agent": agent,
      "arguments": arguments,
      "status": "completed",
      "output": result,
    }
  )
  log_query_event(
    "tool.completed",
    payload={"call_id": call_id, "tool_name": name, "agent": agent, "arguments": arguments, "result": result},
  )
  return result


def validate_project_artifact_from_response(response: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(response, dict):
    raise AgentRuntimeLoopError("Code Agent response must be a JSON object.")
  generated_website = response.get("generated_website")
  if not isinstance(generated_website, dict):
    orchestration_flow = response.get("orchestration_flow")
    if isinstance(orchestration_flow, dict):
      generated_website = orchestration_flow.get("generated_website")
  if not isinstance(generated_website, dict):
    raise AgentRuntimeLoopError("Code Agent response missing generated_website.")
  try:
    return validate_project_artifact(generated_website)
  except Exception as exc:
    raise AgentRuntimeLoopError(str(exc)) from exc


def deterministic_artifact_response_for_runtime(
  state: dict[str, Any],
  *,
  prompt: str,
  operation: str,
  brief: dict[str, Any],
  plan: dict[str, Any],
  error: Exception,
  action: str,
  strategy: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
  raise AgentRuntimeLoopError(
    "Deterministic artifact fallback is disabled. The existing website must be preserved, "
    "or Gemini must return a valid scoped patch/full artifact."
  )


def record_deterministic_repair_event(
  state: dict[str, Any],
  *,
  strategy: str,
  reason: str,
  paths: list[str] | None = None,
) -> None:
  event = {
    "strategy": strategy,
    "reason": reason[:1200],
    "paths": list(paths or []),
  }
  state.setdefault("deterministic_repair_events", []).append(event)
  log_query_event("runtime.repair.strategy", payload=event)


def restore_previous_project_files(
  state: dict[str, Any],
  *,
  tool_executor: ToolExecutor,
  tool_context: ToolRuntimeContext,
  user: Any,
  project_id: str,
  read_result: dict[str, Any],
) -> dict[str, Any]:
  if not isinstance(read_result.get("files"), list):
    raise AgentRuntimeLoopError("Cannot restore previous project files because no successful READ_PROJECT_FILES snapshot was captured.")
  previous_files = project_files_to_tool_files(read_result.get("files"))
  restore_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent="Repair Agent",
    name="WRITE_PROJECT_FILES",
    arguments={
      "project_id": project_id,
      "files": previous_files,
      "allow_empty": True,
      "mode": "replace_all",
      "allow_prune_missing": True,
      "reason": "rollback_restore",
    },
  )
  append_step(
    state,
    "Repair Agent",
    "restore_previous_project_files",
    {"previous_file_count": len(previous_files)},
    restore_result,
    tool_calls=["WRITE_PROJECT_FILES"],
  )
  state["local_sync"] = restore_result.get("local_sync")
  state["rollback_restored"] = True
  return restore_result
