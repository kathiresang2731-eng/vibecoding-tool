from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any


class TerminalSandboxError(RuntimeError):
  pass


DEFAULT_TIMEOUT_SECONDS = 120
MAX_OUTPUT_CHARS = 120_000

ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
  ("git", "status"),
  ("git", "status", "--short"),
  ("git", "diff"),
  ("git", "diff", "--staged"),
  ("git", "log", "-1", "--oneline"),
  ("python", "-m", "pytest"),
  ("python", "-m", "pytest", "-q"),
  ("npm", "test"),
  ("npm", "run", "build"),
  ("npm", "run", "lint"),
)


def _truncate(text: str) -> str:
  if len(text) <= MAX_OUTPUT_CHARS:
    return text
  return text[: MAX_OUTPUT_CHARS - 40] + "\n...[output truncated]..."


def _normalize_command(command: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
  if isinstance(command, str):
    parts = tuple(shlex.split(command.strip()))
  else:
    parts = tuple(str(part).strip() for part in command if str(part).strip())
  if not parts:
    raise TerminalSandboxError("Command cannot be empty.")
  return parts


def command_is_allowlisted(command: tuple[str, ...]) -> bool:
  if command in ALLOWED_COMMANDS:
    return True
  if len(command) >= 2 and command[:2] == ("git", "status"):
    return True
  if len(command) >= 2 and command[:2] == ("git", "diff"):
    return True
  if len(command) >= 2 and command[:2] == ("git", "add"):
    return True
  if len(command) >= 2 and command[:2] == ("git", "commit"):
    return len(command) >= 4 and command[2] == "-m" and bool(command[3].strip())
  if len(command) >= 3 and command[:3] == ("python", "-m", "pytest"):
    return True
  if len(command) >= 2 and command[:2] == ("npm", "run"):
    return command[2] in {"build", "lint", "test"}
  if len(command) >= 2 and command[:2] == ("npm", "test"):
    return True
  return False


def resolve_workspace_root(workspace: str | Path | None) -> Path:
  if not workspace:
    raise TerminalSandboxError("workspace is required for terminal/git execution.")
  root = (workspace if isinstance(workspace, Path) else Path(str(workspace))).expanduser().resolve(strict=False)
  if not root.exists() or not root.is_dir():
    raise TerminalSandboxError(f"Workspace does not exist: {root}")
  allowed_roots = [
    Path(item).expanduser().resolve(strict=False)
    for item in os.getenv("LOCAL_WORKSPACE_ROOTS", "").split(",")
    if item.strip()
  ]
  if allowed_roots and not any(root == item or item in root.parents for item in allowed_roots):
    raise TerminalSandboxError(f"Workspace {root} is outside LOCAL_WORKSPACE_ROOTS.")
  return root


def run_allowlisted_command(
  workspace: str | Path,
  command: str | list[str] | tuple[str, ...],
  *,
  timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
  normalized = _normalize_command(command)
  if not command_is_allowlisted(normalized):
    raise TerminalSandboxError(f"Command is not allowlisted: {shlex.join(normalized)}")
  root = resolve_workspace_root(workspace)
  try:
    completed = subprocess.run(
      normalized,
      cwd=root,
      text=True,
      capture_output=True,
      timeout=max(1, int(timeout_seconds)),
      check=False,
    )
  except FileNotFoundError as exc:
    raise TerminalSandboxError(f"Executable not found: {normalized[0]}") from exc
  except subprocess.TimeoutExpired as exc:
    return {
      "ok": False,
      "command": list(normalized),
      "workspace": str(root),
      "exit_code": None,
      "timed_out": True,
      "stdout": _truncate(str(exc.stdout or "")),
      "stderr": _truncate(str(exc.stderr or "")),
    }
  return {
    "ok": completed.returncode == 0,
    "command": list(normalized),
    "workspace": str(root),
    "exit_code": completed.returncode,
    "timed_out": False,
    "stdout": _truncate(completed.stdout or ""),
    "stderr": _truncate(completed.stderr or ""),
  }
