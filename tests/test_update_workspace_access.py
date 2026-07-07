from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.generation_parts.workspace_access import (
  ensure_update_workspace_ready,
  prompt_requires_writable_workspace,
)


PROJECT_FILES = [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]


def test_update_prompt_requires_workspace_for_existing_project() -> None:
  assert prompt_requires_writable_workspace("fix the launch button", project_files=PROJECT_FILES) is True
  assert prompt_requires_writable_workspace("build a new website", project_files=PROJECT_FILES) is False


def test_missing_writable_workspace_blocks_update(tmp_path) -> None:
  settings = SimpleNamespace(app_root=tmp_path / "app", local_workspace_roots=[tmp_path])
  project = {"id": "project-1", "name": "Ai Native CRM", "local_path": ""}

  with pytest.raises(HTTPException) as exc_info:
    ensure_update_workspace_ready(
      prompt="fix the launch button",
      project=project,
      project_files=PROJECT_FILES,
      settings=settings,
      client_workspace_access=None,
    )

  assert exc_info.value.status_code == 409
  assert exc_info.value.detail["code"] == "writable_workspace_required"


def test_browser_directory_workspace_proof_allows_update(tmp_path) -> None:
  settings = SimpleNamespace(app_root=tmp_path / "app", local_workspace_roots=[tmp_path])
  project = {"id": "project-1", "name": "Ai Native CRM", "local_path": ""}

  access = ensure_update_workspace_ready(
    prompt="fix the launch button",
    project=project,
    project_files=PROJECT_FILES,
    settings=settings,
    client_workspace_access={"mode": "browser_directory", "connected": True, "writable": True, "name": "DEMO_66"},
  )

  assert access["mode"] == "browser_directory"
  assert access["connected"] is True
  assert access["writable"] is True
