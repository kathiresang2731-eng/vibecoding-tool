import json

from backend.api.v1.events import (
  event_schema_payload,
  make_v1_event,
  translate_legacy_stream_event,
)


def test_event_schema_payload_lists_core_types():
  payload = event_schema_payload()
  assert payload["schema"] == "worktual.run-event.v1"
  assert "run.created" in payload["event_types"]
  assert "run.completed" in payload["event_types"]
  assert "tool.requested" in payload["event_types"]
  assert "gate.failed" in payload["event_types"]


def test_translate_legacy_complete_event():
  event = translate_legacy_stream_event(
    {"type": "complete", "payload": {"ok": True}},
    run_id="run-1",
    workspace_id="ws-1",
    client="cli",
  )
  assert event["type"] == "run.completed"
  assert event["schema"] == "worktual.run-event.v1"
  assert event["run_id"] == "run-1"
  assert event["workspace_id"] == "ws-1"
  assert event["client"] == "cli"
  assert event["payload"] == {"ok": True}


def test_translate_legacy_error_event():
  event = translate_legacy_stream_event(
    {
      "type": "error",
      "user_message": "Backend generation failed.",
      "category": "backend_generation",
      "code": "generation_failed",
      "status": 502,
      "detail": {"raw_error": "timeout"},
    },
    run_id="run-2",
    workspace_id="ws-2",
    client="ide",
  )
  assert event["type"] == "run.failed"
  assert event["message"] == "Backend generation failed."
  assert event["detail"]["category"] == "backend_generation"


def test_translate_legacy_progress_maps_tool_and_gate_events():
  tool_event = translate_legacy_stream_event(
    {
      "type": "progress",
      "step": "tool.completed",
      "message": "READ_PROJECT_FILES finished",
      "status": "completed",
      "detail": {"tool_name": "READ_PROJECT_FILES"},
    },
    run_id="run-3",
    workspace_id="ws-3",
    client="web",
  )
  assert tool_event["type"] == "tool.completed"

  gate_event = translate_legacy_stream_event(
    {
      "type": "progress",
      "step": "validation.failed",
      "message": "Artifact validation failed",
      "status": "failed",
      "detail": {"reason": "missing App.jsx"},
    },
    run_id="run-3",
    workspace_id="ws-3",
    client="web",
  )
  assert gate_event["type"] == "gate.failed"


def test_make_v1_event_includes_schema_and_timestamp():
  event = make_v1_event(
    "run.created",
    run_id="abc",
    workspace_id="proj",
    client="cli",
    message="accepted",
  )
  assert event["schema"] == "worktual.run-event.v1"
  assert event["type"] == "run.created"
  assert event["created_at"]
  assert event["message"] == "accepted"


def test_v1_routes_registered_in_main():
  source = open("backend/main.py", encoding="utf-8").read()
  assert '"/api/v1/runs/stream"' in source
  assert '"/api/v1/runs/cancel"' in source
  assert '"/api/v1/events/schema"' in source


def test_v1_stream_adapter_emits_created_then_translated_events():
  from backend.api.v1.models import CreateRunRequest
  from backend.api.v1.runs import v1_runs_stream_events

  class _FakeStore:
    def create_generation_run(self, *args, **kwargs):
      return {"id": "gen-1"}

  class _FakeContext:
    store = _FakeStore()

  class _FakeUser:
    id = "user-1"

  def _fake_pipeline(project_id, prompt, context, user, **kwargs):
    progress = kwargs.get("progress_callback")
    if progress:
      progress({"step": "backend.starting", "message": "Starting", "status": "running"})
    return {"orchestration_flow": {"generated_website": {"files": []}}}

  lines = list(
    v1_runs_stream_events(
      CreateRunRequest(workspace_id="proj-1", prompt="build landing page", client="cli"),
      _FakeContext(),
      _FakeUser(),
      run_generation_pipeline=_fake_pipeline,
    )
  )
  assert len(lines) >= 2
  first = json.loads(lines[0])
  assert first["type"] == "run.created"
  assert first["client"] == "cli"
  assert any('"type": "run.completed"' in line or '"type": "run.progress"' in line for line in lines[1:])
