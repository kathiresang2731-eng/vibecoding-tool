from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.automation_tests import resolve_screenshot_file
from backend.storage.bootstrap import BOOTSTRAP_STATEMENTS
from backend.visual_qa.artifacts import screenshot_file_metadata, screenshot_run_directory
from backend.visual_qa.impact import build_automated_test_scope
from backend.visual_qa.persistence import persist_visual_qa_result


def test_changed_component_maps_to_dependent_page_route():
  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import Dashboard from "./pages/Dashboard";\n'
        'export default function App(){ return <Route path="/dashboard" element={<Dashboard />} />; }\n'
      ),
    },
    {
      "path": "src/pages/Dashboard.jsx",
      "content": 'import Stats from "../components/Stats";\nexport default function Dashboard(){ return <Stats />; }\n',
    },
    {
      "path": "src/components/Stats.jsx",
      "content": "export default function Stats(){ return <section>42</section>; }\n",
    },
  ]

  scope = build_automated_test_scope(
    files,
    changed_paths=["src/components/Stats.jsx"],
    operation="update",
    prompt="Update the dashboard stats card",
  )

  assert scope["scope"] == "targeted"
  assert scope["affected_routes"] == ["/dashboard"]
  assert "src/pages/Dashboard.jsx" in scope["affected_files"]


def test_global_styles_trigger_full_visual_scope():
  scope = build_automated_test_scope(
    [{"path": "src/index.css", "content": "body { color: black; }"}],
    changed_paths=["src/index.css"],
    operation="update",
    prompt="Change global spacing",
  )

  assert scope["scope"] == "full"
  assert scope["full_build"] is True
  assert scope["affected_routes"] == ["/"]


def test_screenshot_run_directory_and_hash_are_stable(tmp_path):
  settings = SimpleNamespace(screenshot_storage_root=tmp_path)
  directory = screenshot_run_directory(
    settings,
    project_id="project/unsafe",
    chat_session_id="session:1",
    test_run_id="run-1",
    phase="after",
    route="/dashboard",
  )
  screenshot = directory / "mobile.png"
  screenshot.write_bytes(b"png-data")

  metadata = screenshot_file_metadata(screenshot)

  assert tmp_path.resolve() in screenshot.resolve().parents
  assert metadata["size_bytes"] == 8
  assert len(metadata["sha256"]) == 64


def test_persist_visual_result_links_before_and_after_artifacts():
  class Store:
    def __init__(self):
      self.artifacts = []
      self.comparisons = []
      self.completed = None

    def latest_baseline_screenshot(self, *_args, **_kwargs):
      return {
        "id": "baseline-1",
        "width": 390,
        "height": 844,
        "storage_path": "/safe/before.png",
        "sha256": "before-hash",
        "size_bytes": 100,
        "project_version_id": "version-before",
      }

    def create_screenshot_artifact(self, _project_id, _user, **kwargs):
      row = {"id": f"artifact-{len(self.artifacts) + 1}", **kwargs}
      self.artifacts.append(row)
      return row

    def create_visual_comparison(self, _project_id, _user, **kwargs):
      row = {"id": "comparison-1", **kwargs}
      self.comparisons.append(row)
      return row

    def complete_automation_test_run(self, _test_run_id, _user, **kwargs):
      self.completed = kwargs
      return {"status": kwargs["status"]}

  store = Store()
  result = persist_visual_qa_result(
    store=store,
    user=SimpleNamespace(id="user-1"),
    test_run={"id": "test-run-1"},
    browser_result={
      "status": "passed",
      "target_url": "http://preview/",
      "layout_checked": True,
      "severity": "none",
      "screenshots": [
        {
          "route": "/",
          "viewport_name": "mobile",
          "width": 390,
          "height": 844,
          "storage_path": "/safe/after.png",
          "sha256": "after-hash",
          "size_bytes": 120,
        }
      ],
      "layout_issues": [],
      "warnings": [],
    },
    project_id="project-1",
    chat_session_id="session-1",
    project_version_id="version-after",
    phase="after",
  )

  assert [item["phase"] for item in store.artifacts] == ["before", "after"]
  assert store.artifacts[0]["source_artifact_id"] == "baseline-1"
  assert store.artifacts[1]["is_baseline"] is True
  assert store.comparisons[0]["changed"] is True
  assert result["status"] == "passed"


def test_screenshot_file_resolution_blocks_paths_outside_storage_root(tmp_path):
  root = tmp_path / "screenshots"
  root.mkdir()
  outside = tmp_path / "outside.png"
  outside.write_bytes(b"outside")

  class Store:
    def get_screenshot_artifact(self, _artifact_id, _user):
      return {"storage_path": str(outside)}

  with pytest.raises(HTTPException, match="outside the configured storage root"):
    resolve_screenshot_file(
      Store(),
      SimpleNamespace(screenshot_storage_root=root),
      SimpleNamespace(id="user-1"),
      artifact_id="artifact-1",
    )


def test_automation_testing_tables_are_bootstrapped():
  schema = "\n".join(BOOTSTRAP_STATEMENTS)

  assert "create table if not exists automation_test_runs" in schema
  assert "create table if not exists screenshot_artifacts" in schema
  assert "create table if not exists visual_comparisons" in schema
