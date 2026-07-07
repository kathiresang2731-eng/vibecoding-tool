from __future__ import annotations

from unittest.mock import MagicMock

from backend.agents.streaming.parallel_orchestrator import run_parallel_stream_orchestrator
from backend.storage import UserContext


def test_greenfield_generation_uses_three_parallel_workers_by_default(monkeypatch):
  captured: dict[str, object] = {}

  def fake_parallel_file_workers(**kwargs):
    captured.update(kwargs)
    return {
      "generated_website": {"files": [], "sections": []},
      "artifact_response": {},
      "runtime": {"engine": "parallel_file_workers", "changed_paths": []},
    }

  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.run_streaming_file_agent",
    lambda **_kwargs: (_ for _ in ()).throw(AssertionError("single streaming agent should not run")),
  )
  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.parallel_greenfield_generation_enabled",
    lambda: False,
  )
  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.run_parallel_file_workers",
    fake_parallel_file_workers,
  )

  store = MagicMock()
  store.list_files.return_value = []
  tool_context = MagicMock()
  tool_context.store = store
  user = UserContext(id="user-1", email="user@example.com", role="user")

  result = run_parallel_stream_orchestrator(
    project_id="project-1",
    user=user,
    tool_context=tool_context,
    prompt="Build a simple landing page for a design studio",
    intent="website_generation",
    artifact_provider=MagicMock(),
    emit_progress=lambda *_args, **_kwargs: None,
  )

  assert captured["work_plan"]["task_count"] == 3
  assert len(captured["work_plan"]["waves"][0]) == 3
  assert result["runtime"]["engine"] == "parallel_file_workers"


def test_rich_greenfield_generation_uses_bounded_parallel_workers_even_when_default_disabled(monkeypatch):
  captured: dict[str, object] = {}

  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.parallel_greenfield_generation_enabled",
    lambda: False,
  )
  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.run_streaming_file_agent",
    lambda **_kwargs: (_ for _ in ()).throw(AssertionError("single streaming agent should not run")),
  )

  def fake_parallel_file_workers(**kwargs):
    captured.update(kwargs)
    return {
      "generated_website": {"files": [], "sections": []},
      "artifact_response": {},
      "runtime": {"engine": "parallel_file_workers", "changed_paths": []},
    }

  monkeypatch.setattr(
    "backend.agents.streaming.parallel_orchestrator.run_parallel_file_workers",
    fake_parallel_file_workers,
  )

  store = MagicMock()
  store.list_files.return_value = [{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}]
  tool_context = MagicMock()
  tool_context.store = store
  user = UserContext(id="user-1", email="user@example.com", role="user")

  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) After auth provide onboarding
  3) dashboard with report analytics
  4) modules: leads and contact, deals, sales, project, product, main ai chat
  """

  result = run_parallel_stream_orchestrator(
    project_id="project-1",
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    intent="website_generation",
    artifact_provider=MagicMock(),
    emit_progress=lambda *_args, **_kwargs: None,
  )

  work_plan = captured["work_plan"]
  paths = {path for task in work_plan["tasks"] for path in task.get("paths") or []}
  assert result["runtime"]["engine"] == "parallel_file_workers"
  assert work_plan["greenfield"] is True
  assert "src/pages/Auth.jsx" in paths
  assert "src/pages/Dashboard.jsx" in paths
  assert "src/pages/Deals.jsx" in paths
