from backend.agents.agent_runtime.patch_staging import stage_candidate_patches_via_apply_patch
from backend.execution.patch import build_unified_patches_from_file_changes
import importlib.util
from pathlib import Path
from types import SimpleNamespace

_events_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "v1" / "events.py"
_events_spec = importlib.util.spec_from_file_location("_v1_events_under_test", _events_path)
assert _events_spec and _events_spec.loader
_events_mod = importlib.util.module_from_spec(_events_spec)
_events_spec.loader.exec_module(_events_mod)
translate_legacy_stream_event = _events_mod.translate_legacy_stream_event


def test_build_unified_patches_from_file_changes():
  existing = [{"path": "src/App.jsx", "content": "alpha\nbeta\ngamma\n"}]
  changed = [{"path": "src/App.jsx", "content": "alpha\nbeta-updated\ngamma\n"}]
  patches = build_unified_patches_from_file_changes(existing, changed)
  assert len(patches) == 1
  assert patches[0]["path"] == "src/App.jsx"
  assert "beta-updated" in patches[0]["unified_diff"]


def test_stage_candidate_patches_via_apply_patch_records_tool_call():
  state: dict = {"tool_calls": [], "changed_file_paths": ["src/App.jsx"]}
  existing = [{"path": "src/App.jsx", "content": "alpha\nbeta\ngamma\n"}]
  changed = [{"path": "src/App.jsx", "content": "alpha\nbeta-updated\ngamma\n"}]
  events: list[dict] = []

  def tool_executor(name, context, user, arguments):
    if name == "APPLY_PATCH":
      return {
        "status": "staged",
        "patch_set": {"diff_stats": {"paths": ["src/App.jsx"], "additions": 1, "deletions": 1}},
        "files": changed,
      }
    raise AssertionError(name)

  staged_files, patch_set = stage_candidate_patches_via_apply_patch(
    state,
    existing_files=existing,
    changed_files=changed,
    tool_executor=tool_executor,
    tool_context=SimpleNamespace(store=None, settings=None),
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    agent="Scoped Update Agent",
    progress=lambda step, message, **kwargs: events.append({"step": step, **kwargs}),
    stage="test_staged",
  )

  assert staged_files == changed
  assert patch_set["diff_stats"]["paths"] == ["src/App.jsx"]
  assert state["patch_staged"] is True
  assert state["tool_calls"][-1]["name"] == "APPLY_PATCH"
  assert any(event["step"] == "patch.proposed" for event in events)


def test_translate_legacy_patch_proposed_event():
  event = translate_legacy_stream_event(
    {
      "type": "progress",
      "step": "patch.proposed",
      "status": "running",
      "message": "Patch proposed: 1 file(s)",
      "detail": {
        "paths": ["src/App.jsx"],
        "diff_stats": {"additions": 2, "deletions": 1, "paths": ["src/App.jsx"]},
      },
    },
    run_id="run-1",
    workspace_id="project-1",
    client="web",
  )
  assert event["type"] == "patch.proposed"
  assert event["payload"]["paths"] == ["src/App.jsx"]


def test_translate_legacy_file_diff_ready_maps_to_patch_proposed():
  event = translate_legacy_stream_event(
    {
      "type": "progress",
      "step": "file.diff.ready",
      "status": "completed",
      "message": "Prepared code changes",
      "detail": {
        "file_count": 1,
        "added": 2,
        "removed": 1,
        "diffs": [{"path": "src/App.jsx", "diff": "@@ ..."}],
      },
    },
    run_id="run-2",
    workspace_id="project-2",
    client="cli",
  )
  assert event["type"] == "patch.proposed"
  assert event["status"] == "running"
  assert event["payload"]["paths"] == ["src/App.jsx"]


def test_translate_legacy_patch_applied_event():
  event = translate_legacy_stream_event(
    {
      "type": "progress",
      "step": "patch.applied",
      "status": "completed",
      "message": "Committed code changes: 1 file(s)",
      "detail": {"paths": ["src/App.jsx"], "file_count": 1},
    },
    run_id="run-3",
    workspace_id="project-3",
    client="ide",
  )
  assert event["type"] == "patch.applied"
  assert event["status"] == "completed"
