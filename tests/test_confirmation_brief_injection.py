from __future__ import annotations

from unittest.mock import MagicMock

from backend.agents.generation_engine.greenfield_runner import run_website_generation
from backend.storage import UserContext


def test_greenfield_runner_passes_confirmation_brief_to_streaming_agent(monkeypatch) -> None:
  captured: dict[str, object] = {}

  def fake_streaming_file_agent(**kwargs):
    captured.update(kwargs)
    return {
      "generated_website": {
        "files": [
          {"path": "src/pages/Auth.jsx", "content": "export default function Auth(){return <div/>}"},
          {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){return <div/>}"},
          {"path": "src/App.jsx", "content": "import Auth from './pages/Auth'; import Dashboard from './pages/Dashboard'; import { Routes, Route } from 'react-router-dom'; export default function App(){return <Routes><Route path='/auth' element={<Auth/>}/><Route path='/dashboard' element={<Dashboard/>}/></Routes>}"},
        ],
        "summary": "done",
      },
      "artifact_response": {},
      "runtime": {"engine": "streaming_file_agent", "changed_paths": ["src/pages/Auth.jsx"]},
    }

  monkeypatch.setattr(
    "backend.agents.generation_engine.greenfield_runner.run_streaming_file_agent",
    fake_streaming_file_agent,
  )
  monkeypatch.setattr(
    "backend.agents.generation_engine.greenfield_runner.greenfield_parallel_workers_enabled",
    lambda: False,
  )
  monkeypatch.setattr(
    "backend.agents.generation_engine.greenfield_runner._inject_vite_scaffold_if_needed",
    lambda **_kwargs: [],
  )

  store = MagicMock()
  store.list_files.return_value = [
    {"path": "src/pages/Auth.jsx", "content": "export default function Auth(){return <div/>}"},
    {"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){return <div/>}"},
    {"path": "src/App.jsx", "content": "import Auth from './pages/Auth'; import Dashboard from './pages/Dashboard'; import { Routes, Route } from 'react-router-dom'; export default function App(){return <Routes><Route path='/auth' element={<Auth/>}/><Route path='/dashboard' element={<Dashboard/>}/></Routes>}"},
  ]
  tool_context = MagicMock()
  tool_context.store = store
  user = UserContext(id="user-1", email="user@example.com", role="user")

  brief = {
    "summary": "AI CRM build",
    "planned_changes": ["Generate auth and dashboard"],
    "assumptions": ["React frontend"],
    "scope_boundaries": ["Keep unrelated files untouched"],
  }
  run_website_generation(
    project_id="project-1",
    user=user,
    tool_context=tool_context,
    prompt="Build a simple landing page",
    artifact_provider=MagicMock(),
    emit_progress=lambda *_args, **_kwargs: None,
    confirmation_brief=brief,
  )

  assert captured.get("confirmation_brief") == brief
  assert "Greenfield build blueprint" in str(captured.get("prompt") or "")
