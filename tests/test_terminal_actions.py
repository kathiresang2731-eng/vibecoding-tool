"""Tests for Worktual local helper terminal actions."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from local_helper.terminal_actions import (
    TerminalActionError,
    list_terminal_actions,
    resolve_workspace,
    run_terminal_action,
)

from agents.chat_history import latest_error_context


def test_list_terminal_actions_includes_safe_defaults():
    names = {item["name"] for item in list_terminal_actions()}
    assert {"git_status", "git_diff", "python_tests", "frontend_build", "npm_test"}.issubset(names)
    assert {
        "frontend_install",
        "frontend_install_and_build",
        "python_install_requirements",
        "python_install_and_test",
    }.issubset(names)


def test_resolve_workspace_allows_paths_inside_home(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert resolve_workspace(str(workspace), home=tmp_path) == workspace


def test_resolve_workspace_rejects_paths_outside_home(tmp_path):
    outside = tmp_path.parent / "outside-worktual-helper-test"
    outside.mkdir(exist_ok=True)
    with pytest.raises(TerminalActionError):
        resolve_workspace(str(outside), home=tmp_path)


def test_custom_command_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS", raising=False)
    with pytest.raises(TerminalActionError):
        run_terminal_action({"action": "custom", "command": "pwd", "workspace": str(tmp_path)}, home=tmp_path)


def test_custom_command_can_run_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKTUAL_HELPER_ALLOW_CUSTOM_COMMANDS", "1")
    result = run_terminal_action(
        {
            "action": "custom",
            "command": ["python", "-c", "print('ok')"],
            "workspace": str(tmp_path),
        },
        home=tmp_path,
    )
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "ok"


def test_unknown_action_is_rejected(tmp_path):
    with pytest.raises(TerminalActionError):
        run_terminal_action({"action": "rm_everything", "workspace": str(tmp_path)}, home=tmp_path)


def test_frontend_install_and_build_runs_install_then_retry(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout=f"{' '.join(command)} ok\n", stderr="")

    monkeypatch.setattr("local_helper.terminal_actions.subprocess.run", fake_run)

    result = run_terminal_action({"action": "frontend_install_and_build", "workspace": str(tmp_path)}, home=tmp_path)

    assert result["ok"] is True
    assert calls == [("npm", "install", "--ignore-scripts"), ("npm", "run", "build")]
    assert result["commands"] == [["npm", "install", "--ignore-scripts"], ["npm", "run", "build"]]
    assert len(result["steps"]) == 2


def test_install_and_retry_stops_when_install_fails(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="install failed\n")

    monkeypatch.setattr("local_helper.terminal_actions.subprocess.run", fake_run)

    result = run_terminal_action({"action": "frontend_install_and_build", "workspace": str(tmp_path)}, home=tmp_path)

    assert result["ok"] is False
    assert calls == [("npm", "install", "--ignore-scripts")]
    assert result["exit_code"] == 1
    assert "install failed" in result["stderr"]


def test_local_environment_error_is_orchestrator_error_context():
    context = latest_error_context(
        [
            {
                "role": "user",
                "content": (
                    "Local environment error reported by Worktual UI.\n"
                    "Operation: install_home_skills\n"
                    "Error: Local skills helper is not reachable.\n"
                    "Orchestrator instruction: route this as a local environment / terminal handling failure."
                ),
            }
        ]
    )
    assert "Local environment error" in context
    assert "terminal handling" in context
