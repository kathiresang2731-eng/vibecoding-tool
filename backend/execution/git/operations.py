from __future__ import annotations

from pathlib import Path
from typing import Any

try:
  from ..terminal.sandbox import TerminalSandboxError, run_allowlisted_command
except ImportError:
  from execution.terminal.sandbox import TerminalSandboxError, run_allowlisted_command


def git_status(workspace: str | Path, *, short: bool = True) -> dict[str, Any]:
  command = ("git", "status", "--short") if short else ("git", "status")
  result = run_allowlisted_command(workspace, command, timeout_seconds=60)
  return {"operation": "git_status", **result}


def git_diff(workspace: str | Path, *, staged: bool = False) -> dict[str, Any]:
  command = ("git", "diff", "--staged") if staged else ("git", "diff")
  result = run_allowlisted_command(workspace, command, timeout_seconds=60)
  return {"operation": "git_diff", **result}


def git_commit(workspace: str | Path, *, message: str, approved: bool = False) -> dict[str, Any]:
  cleaned = str(message or "").strip()
  if not cleaned:
    raise TerminalSandboxError("Commit message is required.")
  if not approved:
    return {
      "operation": "git_commit",
      "ok": False,
      "status": "approval_required",
      "requires_approval": True,
      "message": "GIT_COMMIT requires explicit approval.",
      "commit_message": cleaned,
    }
  add_result = run_allowlisted_command(workspace, ("git", "add", "-A"), timeout_seconds=60)
  if not add_result.get("ok"):
    return {"operation": "git_commit", "stage": add_result, "ok": False}
  commit_result = run_allowlisted_command(
    workspace,
    ("git", "commit", "-m", cleaned),
    timeout_seconds=60,
  )
  return {"operation": "git_commit", "stage": add_result, "commit": commit_result, "ok": bool(commit_result.get("ok"))}
