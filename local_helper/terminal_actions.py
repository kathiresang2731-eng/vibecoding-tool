"""Safe terminal workflows for the Worktual local helper."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 120_000


class TerminalActionError(ValueError):
    pass


@dataclass(frozen=True)
class TerminalAction:
    name: str
    description: str
    command: tuple[str, ...]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "command": list(self.command),
            "timeout_seconds": self.timeout_seconds,
        }


TERMINAL_ACTIONS: dict[str, TerminalAction] = {
    "git_status": TerminalAction(
        name="git_status",
        description="Show local git status for the selected workspace.",
        command=("git", "status", "--short"),
        timeout_seconds=60,
    ),
    "git_diff": TerminalAction(
        name="git_diff",
        description="Show unstaged and staged git diff for review before commit.",
        command=("git", "diff"),
        timeout_seconds=60,
    ),
    "python_tests": TerminalAction(
        name="python_tests",
        description="Run Python tests with pytest.",
        command=("python", "-m", "pytest"),
    ),
    "frontend_build": TerminalAction(
        name="frontend_build",
        description="Run the frontend production build.",
        command=("npm", "run", "build"),
    ),
    "npm_test": TerminalAction(
        name="npm_test",
        description="Run npm test.",
        command=("npm", "test"),
    ),
    "frontend_install": TerminalAction(
        name="frontend_install",
        description="Install frontend dependencies with npm install while skipping package lifecycle scripts.",
        command=("npm", "install", "--ignore-scripts"),
        timeout_seconds=900,
    ),
    "frontend_install_and_build": TerminalAction(
        name="frontend_install_and_build",
        description="Install frontend dependencies locally, then retry the production build.",
        command=("npm", "install", "--ignore-scripts"),
        timeout_seconds=1200,
    ),
    "python_install_requirements": TerminalAction(
        name="python_install_requirements",
        description="Install Python dependencies from requirements.txt.",
        command=("python", "-m", "pip", "install", "-r", "requirements.txt"),
        timeout_seconds=900,
    ),
    "python_install_and_test": TerminalAction(
        name="python_install_and_test",
        description="Install Python dependencies from requirements.txt, then retry pytest.",
        command=("python", "-m", "pip", "install", "-r", "requirements.txt"),
        timeout_seconds=1200,
    ),
}

TERMINAL_ACTION_WORKFLOWS: dict[str, tuple[tuple[str, ...], ...]] = {
    "frontend_install_and_build": (
        ("npm", "install", "--ignore-scripts"),
        ("npm", "run", "build"),
    ),
    "python_install_and_test": (
        ("python", "-m", "pip", "install", "-r", "requirements.txt"),
        ("python", "-m", "pytest"),
    ),
}


def list_terminal_actions() -> list[dict[str, Any]]:
    actions = []
    for action in TERMINAL_ACTIONS.values():
        item = action.to_dict()
        workflow = TERMINAL_ACTION_WORKFLOWS.get(action.name)
        if workflow and len(workflow) > 1:
            item["commands"] = [list(command) for command in workflow]
        actions.append(item)
    if custom_commands_enabled():
        actions.append(
            {
                "name": "custom",
                "description": "Run a custom command. Disabled unless WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS=1.",
                "command": [],
                "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
            }
        )
    return actions


def custom_commands_enabled() -> bool:
    return os.environ.get("WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS", "").strip().lower() in {"1", "true", "yes", "on"}


def allowed_roots(home: Path | None = None) -> list[Path]:
    user_home = (home or Path.home()).resolve(strict=False)
    roots = [user_home]
    configured = os.environ.get("WORKTUAL_HELPER_ALLOWED_ROOTS", "").strip()
    for raw in configured.split(":"):
        if raw.strip():
            roots.append(Path(raw.strip()).expanduser().resolve(strict=False))
    return roots


def resolve_workspace(value: str | None, *, home: Path | None = None) -> Path:
    if not value or not str(value).strip():
        return (home or Path.home()).resolve(strict=False)
    workspace = Path(str(value).strip()).expanduser().resolve(strict=False)
    roots = allowed_roots(home)
    if not any(workspace == root or root in workspace.parents for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise TerminalActionError(f"Workspace is outside allowed roots: {workspace}. Allowed roots: {allowed}")
    if not workspace.exists() or not workspace.is_dir():
        raise TerminalActionError(f"Workspace does not exist or is not a directory: {workspace}")
    return workspace


def resolve_command(payload: dict[str, Any]) -> tuple[str, tuple[str, ...], int]:
    action_name = str(payload.get("action") or "").strip()
    if not action_name:
        raise TerminalActionError("Terminal action is required.")

    if action_name == "custom":
        if not custom_commands_enabled():
            raise TerminalActionError("Custom commands are disabled. Set WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS=1 to enable them.")
        raw_command = payload.get("command")
        if isinstance(raw_command, str):
            command = tuple(shlex.split(raw_command))
        elif isinstance(raw_command, list):
            command = tuple(str(part) for part in raw_command if str(part).strip())
        else:
            raise TerminalActionError("Custom command must be a string or list.")
        if not command:
            raise TerminalActionError("Custom command cannot be empty.")
        return action_name, command, _timeout_from_payload(payload, DEFAULT_TIMEOUT_SECONDS)

    action = TERMINAL_ACTIONS.get(action_name)
    if action is None:
        raise TerminalActionError(f"Unknown terminal action: {action_name}")
    return action.name, action.command, _timeout_from_payload(payload, action.timeout_seconds)


def run_terminal_action(payload: dict[str, Any], *, home: Path | None = None) -> dict[str, Any]:
    action_name, command, timeout = resolve_command(payload)
    workspace = resolve_workspace(payload.get("workspace"), home=home)
    commands = TERMINAL_ACTION_WORKFLOWS.get(action_name, (command,))
    steps: list[dict[str, Any]] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    final_exit_code: int | None = 0
    timed_out = False

    for index, step_command in enumerate(commands, start=1):
        label = shlex.join(step_command)
        try:
            completed = subprocess.run(
                step_command,
                cwd=workspace,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TerminalActionError(f"Command executable not found: {step_command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
            timed_out = True
            final_exit_code = None
            steps.append(
                {
                    "command": list(step_command),
                    "exit_code": None,
                    "timed_out": True,
                    "stdout": _truncate(stdout),
                    "stderr": _truncate(stderr),
                }
            )
            stdout_parts.append(_step_output_header(index, label, stdout))
            stderr_parts.append(_step_output_header(index, label, stderr))
            break

        final_exit_code = completed.returncode
        steps.append(
            {
                "command": list(step_command),
                "exit_code": completed.returncode,
                "timed_out": False,
                "stdout": _truncate(completed.stdout),
                "stderr": _truncate(completed.stderr),
            }
        )
        stdout_parts.append(_step_output_header(index, label, completed.stdout))
        stderr_parts.append(_step_output_header(index, label, completed.stderr))
        if completed.returncode != 0:
            break

    if len(commands) == 1 and steps:
        stdout = steps[0]["stdout"]
        stderr = steps[0]["stderr"]
    else:
        stdout = _truncate("\n".join(part for part in stdout_parts if part).strip())
        stderr = _truncate("\n".join(part for part in stderr_parts if part).strip())

    return {
        "ok": final_exit_code == 0 and not timed_out,
        "action": action_name,
        "command": list(command),
        "commands": [list(item) for item in commands],
        "workspace": str(workspace),
        "exit_code": final_exit_code,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "steps": steps,
    }


def _step_output_header(index: int, label: str, output: str) -> str:
    if not output:
        return f"$ {label}"
    return f"$ {label}\n{output.rstrip()}"


def _timeout_from_payload(payload: dict[str, Any], fallback: int) -> int:
    try:
        value = int(payload.get("timeout_seconds") or fallback)
    except (TypeError, ValueError):
        value = fallback
    return min(max(value, 1), 1800)


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    suffix = "\n... output truncated by Worktual local helper ...\n"
    return value[: MAX_OUTPUT_CHARS - len(suffix)] + suffix
