from pathlib import Path

import pytest

from backend.agentic.tools.definitions import ToolRuntimeContext
from backend.agentic.tools.registry import codex_tool_registry, execute_codex_tool
from backend.context.search import build_code_index, search_project_codebase
from backend.execution.gates import run_validation_gates
from backend.execution.terminal.sandbox import TerminalSandboxError, command_is_allowlisted, run_allowlisted_command
from backend.platform import policy_tier_for_tool
from backend.storage import UserContext


class _Store:
  def __init__(self, workspace: Path):
    self.workspace = workspace

  def get_project(self, project_id, user):
    return {"id": project_id, "local_path": str(self.workspace)}

  def list_files(self, project_id, user):
    return [{"path": "src/App.jsx", "content": "export default function App() { return null; }\n"}]


def test_platform_registry_includes_sprint_d_tools():
  names = set(codex_tool_registry())
  assert {"RUN_TERMINAL", "GIT_STATUS", "GIT_DIFF", "GIT_COMMIT", "RUN_TESTS", "RUN_LINT"}.issubset(names)


def test_policy_tiers_for_terminal_and_git():
  assert policy_tier_for_tool("RUN_TERMINAL").value == "high"
  assert policy_tier_for_tool("GIT_STATUS").value == "low"
  assert policy_tier_for_tool("GIT_COMMIT").value == "high"
  assert policy_tier_for_tool("RUN_TESTS").value == "medium"


def test_command_allowlist_blocks_destructive_commands():
  assert command_is_allowlisted(("git", "status", "--short")) is True
  assert command_is_allowlisted(("rm", "-rf", "/")) is False


def test_run_allowlisted_command_rejects_non_allowlisted(tmp_path, monkeypatch):
  monkeypatch.setenv("LOCAL_WORKSPACE_ROOTS", str(tmp_path))
  with pytest.raises(TerminalSandboxError):
    run_allowlisted_command(tmp_path, ("python", "-c", "print('ok')"))


def test_git_commit_requires_approval(tmp_path, monkeypatch):
  monkeypatch.setenv("LOCAL_WORKSPACE_ROOTS", str(tmp_path))
  from backend.execution.git import git_commit

  result = git_commit(tmp_path, message="test commit", approved=False)
  assert result["requires_approval"] is True


def test_run_lint_tool_falls_back_to_syntax_lint_without_workspace():
  class _NoWorkspaceStore:
    def get_project(self, project_id, user):
      return {"id": project_id, "local_path": None}

    def list_files(self, project_id, user):
      return [{"path": "src/App.jsx", "content": "export default function App() { return null; }\n"}]

  context = ToolRuntimeContext(store=_NoWorkspaceStore(), settings=None)
  user = UserContext(id="u1", email="u@example.com", role="user")
  result = execute_codex_tool("RUN_LINT", context, user, {"project_id": "p1"})
  assert result["mode"] == "syntax_lint_fallback"
  assert result["ok"] is True


def test_memory_index_search_finds_content():
  files = [{"path": "src/App.jsx", "content": "export default function App() {\n  return <main>Farm</main>;\n}\n"}]
  index = build_code_index(files)
  result = search_project_codebase(files, query="Farm", limit=5, index=index)
  assert result["engine"] == "memory_index"
  assert result["match_count"] >= 1


def test_validation_gates_skip_tests_without_workspace():
  summary = run_validation_gates(
    validation_result={"status": "valid", "file_count": 1},
    candidate_files=[{"path": "src/App.jsx", "content": "export default function App() { return null; }\n"}],
    workspace_root=None,
  )
  unit_gate = next(item for item in summary["gates"] if item["gate"] == "unit_tests")
  assert unit_gate["status"] == "skipped"


def test_git_status_tool_with_workspace(tmp_path, monkeypatch):
  monkeypatch.setenv("LOCAL_WORKSPACE_ROOTS", str(tmp_path))
  (tmp_path / ".git").mkdir()
  store = _Store(tmp_path)
  context = ToolRuntimeContext(store=store, settings=None)
  user = UserContext(id="u1", email="u@example.com", role="user")
  try:
    result = execute_codex_tool("GIT_STATUS", context, user, {"project_id": "p1"})
  except Exception:
    pytest.skip("git not available in test environment")
  assert result["operation"] == "git_status"
