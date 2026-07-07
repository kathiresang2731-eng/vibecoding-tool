from __future__ import annotations

from pathlib import Path
from typing import Any

from .definitions import ToolExecutionError, ToolRuntimeContext
from .platform import _project_files
from .validators import optional_int, required_string

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext


def _project_workspace(context: ToolRuntimeContext, user: UserContext, project_id: str) -> str:
  if context.store is None or not hasattr(context.store, "get_project"):
    raise ToolExecutionError("Project store does not support workspace lookup.")
  project = context.store.get_project(project_id, user)
  if not isinstance(project, dict):
    raise ToolExecutionError(f"Project not found: {project_id}")
  workspace = str(project.get("local_path") or "").strip()
  if not workspace:
    raise ToolExecutionError("Project has no linked local workspace for terminal/git execution.")
  return workspace


def run_terminal_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  command = arguments.get("command")
  if command is None:
    raise ToolExecutionError("command is required.")
  timeout_seconds = optional_int(arguments, "timeout_seconds", fallback=120, minimum=1, maximum=900)
  workspace = _project_workspace(context, user, project_id)
  try:
    from ...execution.terminal import TerminalSandboxError, run_allowlisted_command
  except ImportError:
    from execution.terminal import TerminalSandboxError, run_allowlisted_command
  try:
    result = run_allowlisted_command(workspace, command, timeout_seconds=timeout_seconds)
  except TerminalSandboxError as exc:
    raise ToolExecutionError(str(exc)) from exc
  return {"project_id": project_id, "tool": "RUN_TERMINAL", **result}


def git_status_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  workspace = _project_workspace(context, user, project_id)
  try:
    from ...execution.git import git_status
  except ImportError:
    from execution.git import git_status
  try:
    return {"project_id": project_id, **git_status(workspace)}
  except Exception as exc:
    raise ToolExecutionError(str(exc)) from exc


def git_diff_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  workspace = _project_workspace(context, user, project_id)
  staged = bool(arguments.get("staged"))
  try:
    from ...execution.git import git_diff
  except ImportError:
    from execution.git import git_diff
  try:
    return {"project_id": project_id, **git_diff(workspace, staged=staged)}
  except Exception as exc:
    raise ToolExecutionError(str(exc)) from exc


def git_commit_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  message = required_string(arguments, "message")
  approved = bool(arguments.get("approved"))
  workspace = _project_workspace(context, user, project_id)
  try:
    from ...execution.git import git_commit
  except ImportError:
    from execution.git import git_commit
  try:
    return {"project_id": project_id, **git_commit(workspace, message=message, approved=approved)}
  except Exception as exc:
    raise ToolExecutionError(str(exc)) from exc


def run_tests_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  workspace = _project_workspace(context, user, project_id)
  files = _project_files(context, user, project_id)
  has_pytest = any(str(item.get("path") or "").startswith("tests/") for item in files if isinstance(item, dict))
  command = ("python", "-m", "pytest", "-q") if has_pytest else ("npm", "test")
  try:
    from ...execution.terminal import run_allowlisted_command
  except ImportError:
    from execution.terminal import run_allowlisted_command
  result = run_allowlisted_command(workspace, command, timeout_seconds=optional_int(arguments, "timeout_seconds", fallback=300, minimum=1, maximum=900))
  return {"project_id": project_id, "tool": "RUN_TESTS", "runner": command[0], **result}


def run_lint_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  files = _project_files(context, user, project_id)
  workspace = None
  try:
    workspace = _project_workspace(context, user, project_id)
  except ToolExecutionError:
    workspace = None
  has_package = any(str(item.get("path") or "") == "package.json" for item in files if isinstance(item, dict))
  if workspace and has_package:
    try:
      from ...execution.terminal import run_allowlisted_command
    except ImportError:
      from execution.terminal import run_allowlisted_command
    result = run_allowlisted_command(workspace, ("npm", "run", "lint"), timeout_seconds=120)
    return {"project_id": project_id, "tool": "RUN_LINT", "mode": "npm_run_lint", **result}
  try:
    from ...execution.gates.lint import run_syntax_lint_gate
  except ImportError:
    from execution.gates.lint import run_syntax_lint_gate
  gate = run_syntax_lint_gate(files)
  return {
    "project_id": project_id,
    "tool": "RUN_LINT",
    "mode": "syntax_lint_fallback",
    "ok": gate.status == "passed",
    "exit_code": 0 if gate.status == "passed" else 1,
    "stdout": gate.message,
    "stderr": "" if gate.status == "passed" else str(gate.detail),
    "gate": gate.to_dict(),
  }
