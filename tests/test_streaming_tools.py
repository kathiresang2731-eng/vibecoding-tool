from __future__ import annotations

import pytest

from backend.agentic.tools.definitions import ToolExecutionError, ToolRuntimeContext
from backend.agentic.tools.platform import list_dir_tool, str_replace_tool
from backend.agents.runtime_config import (
  langgraph_runtime_default,
  parallel_stream_orchestrator_enabled,
  streaming_fast_path_enabled,
  streaming_file_agent_enabled,
)
from backend.agents.streaming.file_agent import is_error_repair_prompt
from backend.agents.streaming.parallel_orchestrator import plan_agents_for_request
from backend.storage import UserContext


class _MemoryStore:
  def __init__(self, files: list[dict[str, str]]) -> None:
    self._files = files

  def list_files(self, project_id: str, user: UserContext) -> list[dict[str, str]]:
    return list(self._files)


def test_str_replace_tool_replaces_exact_match() -> None:
  context = ToolRuntimeContext(store=_MemoryStore([{"path": "src/App.jsx", "content": "const title = 'Old';\n"}]), settings=None)  # type: ignore[arg-type]
  user = UserContext(id="user-1", email="dev@example.com", role="user")
  result = str_replace_tool(
    context,
    user,
    {
      "project_id": "proj-1",
      "path": "src/App.jsx",
      "old_string": "const title = 'Old';",
      "new_string": "const title = 'New';",
    },
  )
  assert result["replacements"] == 1
  assert "New" in result["content"]


def test_str_replace_tool_rejects_multiple_matches() -> None:
  context = ToolRuntimeContext(store=_MemoryStore([{"path": "src/App.jsx", "content": "foo\nfoo\n"}]), settings=None)  # type: ignore[arg-type]
  user = UserContext(id="user-1", email="dev@example.com", role="user")
  with pytest.raises(ToolExecutionError, match="matched 2 times"):
    str_replace_tool(
      context,
      user,
      {
        "project_id": "proj-1",
        "path": "src/App.jsx",
        "old_string": "foo",
        "new_string": "bar",
      },
    )


def test_str_replace_tool_rejects_path_escape() -> None:
  context = ToolRuntimeContext(store=_MemoryStore([]), settings=None)  # type: ignore[arg-type]
  user = UserContext(id="user-1", email="dev@example.com", role="user")
  with pytest.raises(Exception):
    str_replace_tool(
      context,
      user,
      {
        "project_id": "proj-1",
        "path": "../etc/passwd",
        "old_string": "a",
        "new_string": "b",
      },
    )


def test_streaming_file_agent_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("ENABLE_STREAMING_FILE_AGENT", raising=False)
  monkeypatch.delenv("AGENTIC_PARITY_TARGET", raising=False)
  assert streaming_file_agent_enabled() is True


def test_streaming_file_agent_enabled_with_high_parity(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("ENABLE_STREAMING_FILE_AGENT", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert streaming_file_agent_enabled() is True


def test_parallel_stream_orchestrator_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("ENABLE_PARALLEL_STREAM_ORCHESTRATOR", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert parallel_stream_orchestrator_enabled() is True


def test_langgraph_runtime_default_at_high_parity(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("RUNTIME_DEFAULT_LANGGRAPH", raising=False)
  monkeypatch.delenv("ENABLE_STREAMING_FAST_PATH", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert langgraph_runtime_default() is True
  assert streaming_fast_path_enabled() is False


def test_streaming_fast_path_disables_langgraph_default(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("ENABLE_STREAMING_FAST_PATH", "true")
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "95")
  assert streaming_fast_path_enabled() is True
  assert langgraph_runtime_default() is False


def test_plan_agents_for_farming_website() -> None:
  plan = plan_agents_for_request("Build a farming website with products and about page", intent="website_generation")
  assert plan["agents"] == ["code"]
  assert plan["specialists"] == []
  assert plan["specialists_skipped"] is True


def test_plan_agents_for_website_update_skips_specialists() -> None:
  plan = plan_agents_for_request("Update the product catalog and cart page", intent="website_update")
  assert plan["agents"] == ["code"]
  assert plan["specialists"] == []
  assert plan["specialists_skipped"] is True


def test_error_repair_prompt_ignores_scoped_design_updates() -> None:
  assert is_error_repair_prompt("Update the preview section background to blue") is False
  assert is_error_repair_prompt("Change the hero headline text") is False
  assert is_error_repair_prompt("Fix the header color to match the logo") is False


def test_error_repair_prompt_detects_real_failures() -> None:
  assert is_error_repair_prompt("Fix this build error: Module not found") is True
  assert is_error_repair_prompt("The submit button doesn't work") is True
  assert is_error_repair_prompt("SyntaxError: Unexpected token") is True


def test_list_dir_tool_returns_unique_child_entries() -> None:
  context = ToolRuntimeContext(
    store=_MemoryStore(
      [
        {"path": "src/components/Navbar.jsx", "content": ""},
        {"path": "src/components/Footer.jsx", "content": ""},
        {"path": "src/components/Auth.jsx", "content": ""},
      ]
    ),
    settings=None,
  )  # type: ignore[arg-type]
  user = UserContext(id="user-1", email="dev@example.com", role="user")
  result = list_dir_tool(context, user, {"project_id": "proj-1", "path": "src/components"})
  assert result["entries"] == ["src/components/Auth.jsx", "src/components/Footer.jsx", "src/components/Navbar.jsx"]
