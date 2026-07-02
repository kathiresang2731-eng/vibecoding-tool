from __future__ import annotations

from typing import Any

from .lint import run_syntax_lint_gate
from .types import GateResult
from .workspace import run_unit_test_gate


def _artifact_validation_gate(validation_result: dict[str, Any] | None) -> GateResult:
  payload = validation_result if isinstance(validation_result, dict) else {}
  status = str(payload.get("status") or "").strip().lower()
  if status == "valid":
    return GateResult(
      gate="artifact_validation",
      status="passed",
      message="Project artifact validation passed.",
      detail={"file_count": payload.get("file_count"), "paths": payload.get("paths")},
    )
  issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
  return GateResult(
    gate="artifact_validation",
    status="failed",
    category="artifact_validation",
    message=str(payload.get("message") or "Project artifact validation failed."),
    detail={"issues": issues[:12], "status": status or "invalid"},
  )


def run_validation_gates(
  *,
  validation_result: dict[str, Any] | None,
  candidate_files: list[dict[str, Any]] | None,
  workspace_root: str | None = None,
) -> dict[str, Any]:
  """Run ordered validation gates after artifact validation tool."""
  gates = [
    _artifact_validation_gate(validation_result),
    run_syntax_lint_gate(candidate_files),
    run_unit_test_gate(workspace_root),
  ]
  failed = next((gate for gate in gates if gate.status == "failed"), None)
  overall = "failed" if failed else "passed"
  return {
    "status": overall,
    "gates": [gate.to_dict() for gate in gates],
    "failed_gate": failed.to_dict() if failed else None,
    "passed_count": sum(1 for gate in gates if gate.status == "passed"),
    "failed_count": sum(1 for gate in gates if gate.status == "failed"),
  }
