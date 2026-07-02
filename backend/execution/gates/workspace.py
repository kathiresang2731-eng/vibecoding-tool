from __future__ import annotations

from typing import Any

from .types import GateResult


def run_unit_test_gate(workspace_root: str | None) -> GateResult:
  if not workspace_root or not str(workspace_root).strip():
    return GateResult(
      gate="unit_tests",
      status="skipped",
      message="No linked workspace; unit test gate skipped.",
    )
  try:
    from ..terminal.sandbox import run_allowlisted_command
  except ImportError:
    from execution.terminal.sandbox import run_allowlisted_command
  try:
    result = run_allowlisted_command(workspace_root, ("python", "-m", "pytest", "-q"), timeout_seconds=180)
  except Exception as exc:
    return GateResult(
      gate="unit_tests",
      status="failed",
      category="test_runner_error",
      message=str(exc),
    )
  if result.get("timed_out"):
    return GateResult(
      gate="unit_tests",
      status="failed",
      category="test_timeout",
      message="Unit tests timed out.",
      detail=result,
    )
  if result.get("ok"):
    return GateResult(gate="unit_tests", status="passed", message="Unit tests passed.", detail=result)
  return GateResult(
    gate="unit_tests",
    status="failed",
    category="test_failure",
    message="Unit tests failed.",
    detail=result,
  )
