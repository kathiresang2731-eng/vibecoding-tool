import asyncio
import json

from fastapi import HTTPException

from backend import main as backend_main


def test_normalize_generation_model_accepts_gemini_35_flash():
  assert backend_main.normalize_generation_model("gemini-3.5-flash") == "gemini-3.5-flash"


def test_generation_failure_payload_classifies_gemini_connection_error():
  payload = backend_main.generation_failure_payload(RuntimeError("Code artifact validation failed: Connection error."))

  assert payload["category"] == "gemini_generation"
  assert payload["code"] == "gemini_connection_failed"
  assert "Gemini artifact generation failed" in payload["error"]
  assert payload["detail"]["provider"] == "gemini"
  assert payload["detail"]["raw_error"] == "Code artifact validation failed: Connection error."


def test_generation_failure_payload_classifies_artifact_model_timeout_as_gemini():
  payload = backend_main.generation_failure_payload(
    RuntimeError("Artifact model call timed out after 45s before a valid artifact was returned.")
  )

  assert payload["category"] == "gemini_generation"
  assert payload["code"] == "gemini_connection_failed"
  assert payload["detail"]["provider"] == "gemini"


def test_generation_failure_payload_classifies_agent_runtime_timeout_separately():
  payload = backend_main.generation_failure_payload(RuntimeError("Agent runtime exceeded timeout budget of 180s."))

  assert payload["category"] == "agent_runtime_timeout"
  assert payload["code"] == "agent_runtime_timeout"
  assert payload["detail"]["provider"] is None
  assert payload["detail"]["runtime_timeout_seconds"] == 180
  assert "runtime budget" in payload["error"]


def test_generation_failure_payload_returns_update_clarification_question():
  message = "Update request needs clarification before editing files: Which catalog component should receive pagination?"
  payload = backend_main.generation_failure_payload(RuntimeError(message))

  assert payload["category"] == "update_clarification"
  assert payload["code"] == "update_needs_clarification"
  assert payload["error"] == message


def test_generation_failure_payload_classifies_scoped_update_guard():
  payload = backend_main.generation_failure_payload(
    RuntimeError("Scoped update attempted to modify unapproved file src/Other.jsx.")
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_unapproved_file"
  assert "outside the approved scope" in payload["error"]


def test_generation_failure_payload_classifies_scoped_update_no_patch():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Scoped update was blocked before project modification: "
      "Gemini returned no scoped edits or changed files for the approved files."
    )
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_no_patch"
  assert "did not return a usable scoped patch" in payload["error"]


def test_generation_failure_payload_classifies_scoped_update_invalid_json():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Scoped update was blocked before project modification: "
      "Gemini returned invalid scoped patch JSON after strict JSON retry. The existing website was preserved."
    )
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_invalid_json"
  assert "malformed scoped patch JSON" in payload["error"]


def test_generation_failure_payload_classifies_scoped_update_rewrite_too_broad():
  payload = backend_main.generation_failure_payload(
    RuntimeError("Scoped update attempted to rewrite too much of src/App.jsx (82% changed; allowed 80%).")
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_rewrite_too_broad"
  assert "rewrite too much" in payload["error"]


def test_generation_failure_payload_classifies_scoped_update_exact_match_failure():
  payload = backend_main.generation_failure_payload(
    RuntimeError("Scoped update edit for src/App.jsx expected 1 exact match(es) but found 0.")
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_exact_match_failed"
  assert "did not match" in payload["error"]


def test_generation_failure_payload_includes_generic_scoped_guard_reason():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Scoped update replacement count for src/components/OnboardingWizard.jsx is outside the safe limit. "
      "The existing website was preserved."
    )
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_guard_failed"
  assert "outside the safe limit" in payload["error"]
  assert payload["error"].endswith("The existing website was preserved.")


def test_generation_failure_payload_classifies_commit_gate_no_change_as_no_patch():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Targeted update could not be applied safely because no effective file changes passed the commit gates. "
      "request_kind=theme_color_update; candidate_files=src/App.jsx; target_files=src/App.jsx."
    )
  )

  assert payload["category"] == "scoped_update_guard"
  assert payload["code"] == "scoped_update_no_patch"
  assert "usable scoped patch" in payload["error"]


def test_generation_failure_payload_reports_rollback_completed():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Agent loop failed after repair budget; restored previous project files: "
      "Preview Agent tool BUILD_STAGED_PROJECT_PREVIEW failed: Vite process crashed"
    )
  )

  assert payload["category"] == "rollback"
  assert payload["code"] == "rollback_completed"
  assert payload["detail"]["rollback_completed"] is True
  assert "Previous project files were restored" in payload["error"]
  assert "staged preview build failed" in payload["error"]


def test_generation_failure_payload_classifies_local_control_model_http_error():
  payload = backend_main.generation_failure_payload(
    HTTPException(status_code=503, detail="Local control model is required but unavailable: local provider missing")
  )

  assert payload["status"] == 503
  assert payload["category"] == "local_control_model"
  assert payload["code"] == "local_control_model_unavailable"
  assert "Local GPT control model is unavailable" in payload["error"]


def test_generation_failure_payload_classifies_local_control_model_connection_error():
  payload = backend_main.generation_failure_payload(
    RuntimeError("Local GPT control model call failed during route_generation_action: Connection error.")
  )

  assert payload["category"] == "local_control_model"
  assert payload["code"] == "local_control_model_connection_failed"
  assert payload["detail"]["provider"] == "local-gpt"
  assert "LOCAL_MODEL_ENDPOINT" in payload["error"]


def test_generation_failure_payload_does_not_blame_generic_connection_on_local_gpt():
  payload = backend_main.generation_failure_payload(RuntimeError("A model connection failed during generation."))

  assert payload["category"] == "model_connection"
  assert payload["code"] == "model_connection_failed"
  assert payload["detail"]["provider"] == "unknown-model"
  assert "configured model endpoints" in payload["error"]


def test_generation_failure_payload_prefers_artifact_context_over_local_control_text():
  payload = backend_main.generation_failure_payload(
    RuntimeError(
      "Agent loop failed after repair budget; restored previous project files: "
      "Code artifact validation failed: Local GPT control model call failed during prompt_analyst_agent: Connection error."
    )
  )

  assert payload["category"] == "rollback"
  assert payload["code"] == "rollback_completed"
  assert "artifact validation failed" in payload["error"]
  assert payload["detail"]["rollback_completed"] is True


def test_failed_progress_event_prints_meaningful_terminal_summary(capsys):
  backend_main.emit_progress(
    None,
    "generation.failed",
    "Generated files failed the staged Vite preview build. No generated files were committed.",
    status="failed",
    detail={
      "category": "preview_build",
      "code": "preview_build_failed",
      "repair_reason": "Preview runtime scan failed: unsafe bare React reference.",
      "raw_error": "long internal traceback should be compacted",
    },
  )

  output = capsys.readouterr().out
  assert "[WorktualRuntime] FAILED generation.failed" in output
  assert "preview_build_failed" in output
  assert "unsafe bare React" in output


def test_failed_progress_event_prints_runtime_timeout_debug_fields(capsys):
  backend_main.emit_progress(
    None,
    "generation.failed",
    "Generation exceeded the backend runtime budget before files could be committed.",
    status="failed",
    detail={
      "category": "agent_runtime_timeout",
      "code": "agent_runtime_timeout",
      "last_runtime_step": "backend.waiting",
      "elapsed_seconds": 181.2,
      "runtime_timeout_seconds": 180,
      "repair_reason": "Preview build failed before final commit.",
      "raw_error": "Agent runtime exceeded timeout budget of 180s.",
    },
  )

  output = capsys.readouterr().out
  assert "[WorktualRuntime] FAILED generation.failed" in output
  assert "agent_runtime_timeout" in output
  assert "backend.waiting" in output
  assert "181.2" in output
  assert "Preview build failed" in output


def test_generate_stream_error_event_uses_structured_failure_payload():
  original_pipeline = backend_main.run_generation_pipeline

  def fake_pipeline(project_id, prompt, context, user, *, progress_callback=None):
    if progress_callback:
      progress_callback({"step": "agent.loop.run_preview_visual_qa", "message": "Running visual QA", "status": "running"})
    raise RuntimeError("Preview visual QA did not pass: No browser command found.")

  async def collect_stream_lines():
    class FakeRequest:
      query_params = {}

      async def json(self):
        return {"prompt": "Build a website"}

      async def body(self):
        return b""

    response = await backend_main.generate_project_stream(
      "project-1",
      FakeRequest(),
      object(),
      type("User", (), {"id": "user-1"})(),
    )
    lines = []
    async for line in response.body_iterator:
      lines.append(json.loads(line.decode() if isinstance(line, bytes) else line))
    return lines

  try:
    backend_main.run_generation_pipeline = fake_pipeline
    lines = asyncio.run(collect_stream_lines())
  finally:
    backend_main.run_generation_pipeline = original_pipeline

  error = next(line for line in lines if line["type"] == "error")
  assert error["status"] == 502
  assert error["category"] == "visual_qa"
  assert error["code"] == "visual_qa_failed"
  assert error["user_message"] == error["error"]
  assert "visual QA failed" in error["error"]
  assert error["detail"]["raw_error"] == "Preview visual QA did not pass: No browser command found."
