from __future__ import annotations

from unittest.mock import MagicMock

from backend.agents.generation_engine.scaffold_persist import _visible_project_files
from backend.storage import UserContext


def test_visible_project_files_keeps_scaffold_paths() -> None:
  files = [
    {"path": "package.json", "content": "{}"},
    {"path": "index.html", "content": "<html></html>"},
    {"path": "src/main.jsx", "content": "export default function Main(){}"},
    {"path": ".worktual/hidden.json", "content": "{}"},
  ]
  visible = _visible_project_files(files)
  paths = {item["path"] for item in visible}
  assert "package.json" in paths
  assert "index.html" in paths
  assert "src/main.jsx" in paths
  assert ".worktual/hidden.json" not in paths


def test_finalize_includes_scaffold_paths_in_generated_website(monkeypatch) -> None:
  from backend.agents.generation_engine import greenfield_runner as runner

  captured: dict[str, object] = {}

  def fake_streaming_file_agent(**kwargs):
    return {
      "generated_website": {"files": [], "summary": "done"},
      "artifact_response": {},
      "runtime": {"engine": "streaming_file_agent", "output_text": "done", "changed_paths": ["src/pages/Home.jsx"]},
    }

  monkeypatch.setattr(runner, "run_streaming_file_agent", fake_streaming_file_agent)
  monkeypatch.setattr(runner, "greenfield_parallel_workers_enabled", lambda: False)
  monkeypatch.setattr(runner, "_inject_vite_scaffold_if_needed", lambda **_kwargs: ["package.json"])

  store = MagicMock()
  store.list_files.return_value = [
    {"path": "package.json", "content": '{"dependencies":{"react":"latest"}}'},
    {"path": "index.html", "content": "<!doctype html><html></html>"},
    {"path": "vite.config.js", "content": "export default {}"},
    {"path": "src/main.jsx", "content": "import App from './App.jsx'; export default function Main(){}"},
    {"path": "src/App.jsx", "content": "import Home from './pages/Home'; import { Routes, Route } from 'react-router-dom'; export default function App(){return <Routes><Route path='/' element={<Home/>}/></Routes>}"},
    {"path": "src/pages/Home.jsx", "content": "export default function Home(){return <div/>}"},
  ]
  tool_context = MagicMock()
  tool_context.store = store
  user = UserContext(id="user-1", email="user@example.com", role="user")

  result = runner.run_website_generation(
    project_id="project-1",
    user=user,
    tool_context=tool_context,
    prompt="Build a landing page",
    artifact_provider=MagicMock(),
    emit_progress=lambda *_args, **_kwargs: None,
  )

  paths = {item.get("path") for item in (result.get("generated_website") or {}).get("files") or []}
  assert "package.json" in paths
  assert "index.html" in paths
  assert "src/main.jsx" in paths
  assert "src/pages/Home.jsx" in paths
