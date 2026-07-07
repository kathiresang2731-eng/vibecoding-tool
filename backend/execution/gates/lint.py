from __future__ import annotations

from typing import Any

from .types import GateResult


def run_syntax_lint_gate(files: list[dict[str, Any]] | None) -> GateResult:
  """Lightweight syntax/structure checks before preview/commit."""
  if not isinstance(files, list) or not files:
    return GateResult(
      gate="syntax_lint",
      status="skipped",
      message="No candidate files to lint.",
    )

  issues: list[dict[str, str]] = []
  for item in files:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    content = str(item.get("content") or "")
    if not path:
      continue
    if not content.strip():
      issues.append({"path": path, "issue": "empty_file"})
      continue
    if path.endswith((".jsx", ".tsx", ".js", ".ts")):
      if content.count("{") != content.count("}"):
        issues.append({"path": path, "issue": "unbalanced_braces"})
      if content.count("(") != content.count(")"):
        issues.append({"path": path, "issue": "unbalanced_parens"})
    if path.endswith(".json"):
      try:
        import json

        json.loads(content)
      except json.JSONDecodeError as exc:
        issues.append({"path": path, "issue": f"invalid_json:{exc.msg}"})

  if issues:
    return GateResult(
      gate="syntax_lint",
      status="failed",
      category="syntax_error",
      message=f"Syntax lint failed for {len(issues)} file(s).",
      detail={"issues": issues[:12]},
    )
  return GateResult(
    gate="syntax_lint",
    status="passed",
    message=f"Syntax lint passed for {len(files)} file(s).",
    detail={"file_count": len(files)},
  )
