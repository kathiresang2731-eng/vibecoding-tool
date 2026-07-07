from __future__ import annotations

from pathlib import Path

import pytest

from backend import runtime as runtime_module
from backend.agents.artifacts import ArtifactValidationError, normalize_artifact_path


def test_artifact_path_normalizes_src_relative_and_project_folder_prefix() -> None:
  assert normalize_artifact_path("pages/ProductDetail.jsx") == "src/pages/ProductDetail.jsx"
  assert normalize_artifact_path("components/Navbar.jsx") == "src/components/Navbar.jsx"
  assert normalize_artifact_path("DEMO90/src/pages/Cart.jsx") == "src/pages/Cart.jsx"
  assert normalize_artifact_path("Crm-Project-worktual/index.html") == "index.html"
  assert normalize_artifact_path("Crm-Project-worktual/package.json") == "package.json"
  assert normalize_artifact_path("Crm-Project-worktual/src/App.jsx") == "src/App.jsx"


def test_artifact_path_collapses_repeated_segments() -> None:
  assert normalize_artifact_path("src/components/src/components/Navbar.jsx") == "src/components/Navbar.jsx"
  assert normalize_artifact_path("src/pages/src/pages/Home.jsx") == "src/pages/Home.jsx"


def test_artifact_path_allows_project_skill_files() -> None:
  assert normalize_artifact_path(".worktual/skills/agentic-architerure/SKILL.md") == ".worktual/skills/agentic-architerure/SKILL.md"
  assert normalize_artifact_path(".worktual/skills/skills.md") == ".worktual/skills/skills.md"
  assert normalize_artifact_path(".worktual/AGENTS.md") == ".worktual/AGENTS.md"


def test_artifact_path_rejects_unscoped_worktual_paths() -> None:
  with pytest.raises(ArtifactValidationError):
    normalize_artifact_path(".worktual/terminal_sessions/session.json")


def test_artifact_path_validation_rejects_traversal() -> None:
  with pytest.raises(ArtifactValidationError):
    normalize_artifact_path("../secrets.txt")
  with pytest.raises(ArtifactValidationError):
    normalize_artifact_path("/Crm-Project-worktual/index.html")


def test_artifact_path_does_not_strip_ignored_folders_into_valid_root_files() -> None:
  with pytest.raises(ArtifactValidationError):
    normalize_artifact_path("node_modules/package.json")
  with pytest.raises(ArtifactValidationError):
    normalize_artifact_path("dist/index.html")


def test_normalize_preview_runtime_files_rewrites_router_imports() -> None:
  files = [
    {
      "path": "src/App.jsx",
      "content": 'import { BrowserRouter } from "react-router-dom";\nexport default function App() { return <BrowserRouter />; }',
    },
  ]
  normalized = runtime_module.normalize_preview_runtime_files(files)
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}
  assert "src/worktual-router-shim.jsx" in by_path
  assert 'from "./worktual-router-shim.jsx"' in by_path["src/App.jsx"]
  runtime_module.validate_preview_dependency_imports(Path("/tmp/unused"), normalized)


def test_normalize_preview_runtime_files_rewrites_recharts_imports() -> None:
  files = [
    {
      "path": "src/components/AIDashboard.jsx",
      "content": 'import { PieChart, Pie, Cell } from "recharts";\nexport default function AIDashboard() { return <PieChart><Pie data={[]}><Cell fill="#0f766e" /></Pie></PieChart>; }',
    },
  ]
  normalized = runtime_module.normalize_preview_runtime_files(files)
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}
  assert "src/worktual-recharts-shim.jsx" in by_path
  assert "worktual-recharts-shim.jsx" in by_path["src/components/AIDashboard.jsx"]
  runtime_module.validate_preview_dependency_imports(Path("/tmp/unused"), normalized)


def test_normalize_preview_runtime_files_replaces_placeholder_app_shell_with_routes() -> None:
  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import React from "react";\n'
        "export default function App(){ return <main><h1>Your site is being generated</h1><p>Page modules will replace this shell.</p></main>; }\n"
      ),
    },
    {
      "path": "src/pages/Dashboard.jsx",
      "content": "export default function Dashboard() { return <main>Dashboard</main>; }\n",
    },
    {
      "path": "src/pages/AiChat.jsx",
      "content": "export default function AiChat() { return <main>AI Chat</main>; }\n",
    },
  ]

  normalized = runtime_module.normalize_preview_runtime_files(files, title="AI Native CRM")
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}

  assert "src/worktual-router-shim.jsx" in by_path
  assert "<BrowserRouter>" in by_path["src/App.jsx"]
  assert 'import Dashboard from "./pages/Dashboard.jsx";' in by_path["src/App.jsx"]
  assert 'import AiChat from "./pages/AiChat.jsx";' in by_path["src/App.jsx"]
