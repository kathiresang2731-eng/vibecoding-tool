from __future__ import annotations

from types import SimpleNamespace

from backend.agents.agent_runtime.materialize import (
  file_materialization_sort_key,
  materialize_candidate_files_incrementally,
  pending_materialization_files,
)
from backend.agents.agent_runtime.supervision import available_finalization_actions


def test_pending_materialization_files_detects_new_and_changed_files():
  state = {
    "candidate_files": [
      {"path": "src/App.jsx", "content": "v1"},
      {"path": "package.json", "content": "{}"},
    ],
    "materialized_file_signatures": {"src/App.jsx": "stale"},
  }
  pending = pending_materialization_files(state)
  assert [item["path"] for item in pending] == ["package.json", "src/App.jsx"]


def test_available_finalization_actions_runs_materialize_before_preview():
  state = {
    "generated_website": {"title": "Site", "files": [{"path": "src/App.jsx", "code": "ok"}]},
    "candidate_files": [{"path": "src/App.jsx", "content": "ok"}],
    "dynamic_patch_integrated": True,
    "validation_result": None,
    "preview_result": None,
    "visual_qa_result": None,
    "committed": False,
    "files_materialized": False,
    "memory": None,
    "repair_errors": [],
  }
  actions = available_finalization_actions(state, max_repair_attempts=1)
  assert actions[0]["name"] == "MATERIALIZE_CANDIDATE_FILES"


def test_available_finalization_actions_repairs_failed_visual_qa_after_ready_preview():
  state = {
    "generated_website": {"title": "Site", "files": [{"path": "src/App.jsx", "code": "ok"}]},
    "candidate_files": [{"path": "src/App.jsx", "content": "ok"}],
    "dynamic_patch_integrated": True,
    "validation_result": {"status": "valid"},
    "preview_result": {"version": {"status": "ready"}},
    "visual_qa_result": {
      "status": "failed",
      "severity": "high",
      "layout_issues": [{"type": "overlap", "viewport": "mobile"}],
    },
    "committed": False,
    "files_materialized": True,
    "memory": None,
    "repair_errors": ["Preview layout QA failed: overlap in mobile viewport."],
    "repair_attempts": 0,
  }

  actions = available_finalization_actions(state, max_repair_attempts=1)

  assert actions[0]["name"] == "RUN_REPAIR_AGENT"


def test_file_materialization_sort_key_prioritizes_entry_files():
  files = [
    {"path": "src/components/Hero.jsx", "content": ""},
    {"path": "index.html", "content": ""},
    {"path": "src/App.jsx", "content": ""},
  ]
  assert [item["path"] for item in sorted(files, key=file_materialization_sort_key)] == [
    "index.html",
    "src/App.jsx",
    "src/components/Hero.jsx",
  ]


def test_materialize_filters_scaffold_files_for_standalone_code_update():
  class FakeStore:
    def __init__(self):
      self.written = []

    def list_files(self, project_id, user):
      return [{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}]

    def apply_generated_files(self, project_id, user, files):
      self.written.extend(files)

  state = {
    "operation": "update",
    "candidate_files": [
      {"path": "NeonNumber.java", "content": "public class NeonNumber { /* updated */ }"},
      {"path": "index.html", "content": "<div id='root'></div>"},
      {"path": "package.json", "content": '{"dependencies":{"vite":"latest"}}'},
    ],
    "generated_website": {"files": []},
    "materialized_file_signatures": {},
    "materialized_file_paths": [],
    "patch_action": "approve",
  }
  progress_events = []
  store = FakeStore()

  def record_progress(step, message, **kwargs):
    progress_events.append({"step": step, "message": message, **kwargs})

  materialize_candidate_files_incrementally(
    state,
    tool_executor=lambda *args, **kwargs: {},
    tool_context=SimpleNamespace(store=store, settings=SimpleNamespace()),
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    progress=record_progress,
  )

  assert [item["path"] for item in store.written] == ["NeonNumber.java"]
  assert [item["path"] for item in state["candidate_files"]] == ["NeonNumber.java"]
  assert any(event.get("step") == "files.scaffold_filtered" for event in progress_events)
