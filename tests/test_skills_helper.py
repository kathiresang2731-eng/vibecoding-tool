"""Tests for the local Worktual skills helper."""

from __future__ import annotations

import shutil
import http.server
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from local_helper.skills_helper import InstallError, install_skills, normalize_skill_path


def test_normalize_skill_path_accepts_helper_payload_paths():
    assert normalize_skill_path("greenfield-website/SKILL.md") == Path("greenfield-website/SKILL.md")
    assert normalize_skill_path("skills.md") == Path("skills.md")
    assert normalize_skill_path("worktual-skills/skills.md") == Path("skills.md")
    assert normalize_skill_path(".worktual-skills/session-code-edit/SKILL.md") == Path("session-code-edit/SKILL.md")


@pytest.mark.parametrize("path", ["", "../secret", "/tmp/secret", ".ssh/config", "skill/../../secret"])
def test_normalize_skill_path_rejects_unsafe_paths(path):
    with pytest.raises(InstallError):
        normalize_skill_path(path)


def test_install_skills_writes_inside_user_home_skills_dir(tmp_path):
    result = install_skills(
        [
            {"path": "greenfield-website/SKILL.md", "content": "# Greenfield\n"},
            {"path": "skills.md", "content": "# Index\n"},
        ],
        home=tmp_path,
    )

    assert result["count"] == 2
    assert result["skills_dir"] == str(tmp_path / ".worktual-skills")
    assert (tmp_path / ".worktual-skills" / "greenfield-website" / "SKILL.md").read_text(encoding="utf-8") == "# Greenfield\n"
    assert (tmp_path / ".worktual-skills" / "skills.md").read_text(encoding="utf-8") == "# Index\n"


def test_downloaded_helper_starts_standalone_and_runs_safe_actions(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git is required for the terminal action smoke test.")

    source = Path(__file__).resolve().parents[1] / "local_helper" / "skills_helper.py"
    standalone_helper = tmp_path / "worktual-skills-helper.py"
    standalone_helper.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)

    events: list[tuple[str, object]] = []

    class FakeThreadingHTTPServer:
        def __init__(self, address, handler):
            events.append(("init", address, handler.__name__))

        def serve_forever(self):
            events.append(("serve_forever",))

    monkeypatch.setattr(http.server, "ThreadingHTTPServer", FakeThreadingHTTPServer)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [str(standalone_helper), "--host", "127.0.0.1", "--port", "8799"])

    namespace = runpy.run_path(str(standalone_helper), run_name="__main__")

    assert events == [
        ("init", ("127.0.0.1", 8799), "SkillsHelperHandler"),
        ("serve_forever",),
    ]
    assert "run" in namespace
    assert "SkillsHelperHandler" in namespace
    action_names = {item["name"] for item in namespace["list_terminal_actions"]()}
    assert {"frontend_install_and_build", "python_install_and_test"}.issubset(action_names)
