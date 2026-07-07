from __future__ import annotations

import time
from typing import Any

from ...errors import AgentRuntimeLoopError
from ...values import object_value


def completion_status(state: dict[str, Any]) -> dict[str, Any]:
  preview_status = object_value(state.get("preview")).get("status")
  return {
    "files_exist": bool(state.get("files")),
    "artifact_valid": object_value(state.get("validation_result")).get("status") == "valid",
    "staged_preview_ready": preview_status == "ready",
    "visual_qa_passed": object_value(state.get("visual_qa_result")).get("status") == "passed",
    "files_committed": bool(state.get("committed")),
    "memory_prepared": bool(state.get("memory")),
  }


def completion_proof(state: dict[str, Any]) -> bool:
  status = completion_status(state)
  return all(status.values())


def can_continue_after_timeout_for_finalization(state: dict[str, Any]) -> bool:
  status = completion_status(state)
  expensive_work_done = (
    status["files_exist"]
    and status["artifact_valid"]
    and status["staged_preview_ready"]
    and status["visual_qa_passed"]
  )
  if not expensive_work_done:
    return False
  return not state.get("completed")


def enforce_loop_budget(
  state: dict[str, Any],
  *,
  start_time: float,
  timeout_seconds: int,
  max_tool_calls: int,
) -> None:
  if time.monotonic() - start_time > timeout_seconds:
    if can_continue_after_timeout_for_finalization(state):
      state["runtime_budget_finalization_grace_used"] = True
      return
    raise AgentRuntimeLoopError(f"Agent runtime exceeded timeout budget of {timeout_seconds}s.")
  if len(state.get("tool_calls") or []) > max_tool_calls:
    raise AgentRuntimeLoopError(f"Agent runtime exceeded tool-call budget of {max_tool_calls}.")
