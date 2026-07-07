from __future__ import annotations

from types import SimpleNamespace

from backend.agents.streaming.streaming_visual_qa import run_precommit_automation_gate


class CandidateStore:
  def __init__(self, local_path: str) -> None:
    self.local_path = local_path

  def get_project(self, project_id, user):
    return {"id": project_id, "local_path": self.local_path}


def candidate_context(tmp_path):
  root = tmp_path / "linked"
  source = root / "src" / "App.jsx"
  source.parent.mkdir(parents=True)
  source.write_text("export default function App(){return <p>working</p>}")
  context = SimpleNamespace(
    store=CandidateStore(str(root)),
    settings=SimpleNamespace(app_root=tmp_path, local_workspace_roots=[tmp_path]),
  )
  return context, source


def test_failed_build_restores_last_working_local_file(tmp_path, monkeypatch):
  context, source = candidate_context(tmp_path)
  monkeypatch.setattr(
    "backend.agentic.tools.handlers.build_staged_project_preview_tool",
    lambda *_args, **_kwargs: {"version": {"status": "failed", "build_log": "Syntax error"}},
  )
  events = []

  build, visual = run_precommit_automation_gate(
    project_id="project-1",
    user=SimpleNamespace(id="user-1"),
    tool_context=context,
    candidate_files=[
      {"path": "src/App.jsx", "content": "export default function App(){return <p>candidate</p>}"}
    ],
    changed_paths=["src/App.jsx"],
    operation="update",
    prompt="fix the launch button",
    chat_session_id=None,
    agent_run_id=None,
    emit_progress=lambda step, message, **data: events.append((step, message, data)),
  )

  assert build["status"] == "failed"
  assert visual is None
  assert "working" in source.read_text()
  assert any(step == "local.candidate.rolled_back" for step, _message, _data in events)


def test_passed_build_and_interaction_keep_local_candidate(tmp_path, monkeypatch):
  context, source = candidate_context(tmp_path)
  monkeypatch.setattr(
    "backend.agentic.tools.handlers.build_staged_project_preview_tool",
    lambda *_args, **_kwargs: {
      "version": {
        "id": "version-1",
        "status": "ready",
        "preview_url": "/api/previews/project-1/version-1/",
        "build_log": "built",
      }
    },
  )
  captured = {}

  def passed_visual(_context, _user, arguments):
    captured.update(arguments)
    return {"status": "passed", "automation_test": {"id": "test-1"}}

  monkeypatch.setattr("backend.agentic.tools.handlers.run_preview_visual_qa_tool", passed_visual)

  build, visual = run_precommit_automation_gate(
    project_id="project-1",
    user=SimpleNamespace(id="user-1"),
    tool_context=context,
    candidate_files=[
      {"path": "src/App.jsx", "content": "export default function App(){return <p>candidate</p>}"}
    ],
    changed_paths=["src/App.jsx"],
    operation="update",
    prompt="fix the Launch Operation Hub button",
    chat_session_id=None,
    agent_run_id=None,
    emit_progress=lambda *_args, **_kwargs: None,
  )

  assert build["status"] == "ready"
  assert visual["status"] == "passed"
  assert "candidate" in source.read_text()
  assert captured["interaction_prompt"] == "fix the Launch Operation Hub button"
