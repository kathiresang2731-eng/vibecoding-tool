from __future__ import annotations

import io
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.gemini_client.errors import GeminiClientError
from backend.agents.gemini_client.transport import post_generate_content
from backend.agents.gemini_tool_calling import run_gemini_tool_calling_loop
from backend.agents.providers.gemini import select_model_chat_history, should_escalate_to_pro
from backend.agents.runtime_config import (
  parallel_greenfield_generation_enabled,
  should_use_parallel_website_workflow,
)
from backend.api.run_locks import (
  ProjectGenerationCancelledError,
  acquire_project_run_lock,
  active_project_run,
  cancel_project_run,
  raise_if_project_run_cancelled,
)
from backend.config import load_settings
from backend.runtime_control import raise_if_runtime_cancelled, runtime_cancellation_scope, submit_with_runtime_context


def test_cancel_waits_until_backend_run_has_really_stopped():
  started = threading.Event()
  outcome = {"cancelled": False}

  def worker():
    try:
      with acquire_project_run_lock("cancel-project", user_id="user-1") as run:
        started.set()
        run.cancel_event.wait(timeout=2)
        raise_if_project_run_cancelled(run)
    except ProjectGenerationCancelledError:
      outcome["cancelled"] = True

  thread = threading.Thread(target=worker)
  thread.start()
  assert started.wait(timeout=1)

  cancelled = cancel_project_run("cancel-project", user_id="user-1", wait_seconds=2)

  thread.join(timeout=1)
  assert cancelled is not None
  assert cancelled["cancel_requested"] is True
  assert cancelled["stopped"] is True
  assert cancelled["status"] == "cancelled"
  assert outcome["cancelled"] is True
  assert active_project_run("cancel-project", user_id="user-1") is None


def test_cancel_rejects_stale_run_id_without_stopping_current_run():
  with acquire_project_run_lock("run-id-project", user_id="user-1") as run:
    assert cancel_project_run(
      "run-id-project",
      user_id="user-1",
      run_id="stale-run-id",
    ) is None
    assert run.cancel_event.is_set() is False


def test_transport_retries_transient_http_status_only(monkeypatch):
  monkeypatch.setenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "2")
  attempts = {"count": 0}

  def fake_urlopen(request, timeout):
    attempts["count"] += 1
    if attempts["count"] == 1:
      raise urllib.error.HTTPError(
        request.full_url,
        503,
        "unavailable",
        {"Retry-After": "0"},
        io.BytesIO(b"temporarily unavailable"),
      )
    response = MagicMock()
    response.read.return_value = b'{"candidates":[]}'
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response

  with patch("backend.agents.gemini_client.transport.urllib.request.urlopen", side_effect=fake_urlopen):
    assert post_generate_content(
      {"contents": []},
      api_key="test",
      model="gemini-3.5-flash",
      timeout_seconds=30,
    ) == {"candidates": []}

  assert attempts["count"] == 2


def test_transport_does_not_retry_non_retryable_404(monkeypatch):
  monkeypatch.setenv("GEMINI_NETWORK_RETRY_ATTEMPTS", "3")
  attempts = {"count": 0}

  def fake_urlopen(request, timeout):
    attempts["count"] += 1
    raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, io.BytesIO(b"not found"))

  with patch("backend.agents.gemini_client.transport.urllib.request.urlopen", side_effect=fake_urlopen):
    with pytest.raises(GeminiClientError, match="Gemini API error 404"):
      post_generate_content(
        {"contents": []},
        api_key="test",
        model="gemini-3.5-flash",
        timeout_seconds=30,
      )

  assert attempts["count"] == 1


def test_cancellation_stops_before_tool_execution():
  client = _FakeGeminiClient(
    [
      {
        "candidates": [
          {
            "content": {
              "role": "model",
              "parts": [
                {
                  "functionCall": {
                    "id": "call-1",
                    "name": "WRITE_FILE",
                    "args": {"path": "src/App.jsx"},
                  }
                }
              ],
            }
          }
        ],
        "usageMetadata": {},
      }
    ]
  )
  checks = {"count": 0}
  tool_called = {"value": False}

  def cancellation_check():
    checks["count"] += 1
    if checks["count"] >= 3:
      raise ProjectGenerationCancelledError("cancelled")

  with runtime_cancellation_scope(cancellation_check):
    with pytest.raises(ProjectGenerationCancelledError):
      run_gemini_tool_calling_loop(
        client=client,
        messages=[{"role": "user", "content": "Update the file."}],
        tools=[
          {
            "type": "function",
            "name": "WRITE_FILE",
            "description": "Write a file.",
            "parameters": {"type": "object", "properties": {}},
          }
        ],
        execute_tool=lambda *_args: tool_called.update(value=True),
      )

  assert tool_called["value"] is False


def test_cancellation_context_propagates_to_parallel_workers():
  def cancellation_check():
    raise ProjectGenerationCancelledError("cancelled")

  with runtime_cancellation_scope(cancellation_check):
    with ThreadPoolExecutor(max_workers=1) as executor:
      future = submit_with_runtime_context(executor, raise_if_runtime_cancelled)
      with pytest.raises(ProjectGenerationCancelledError):
        future.result()


def test_adaptive_parallel_policy_keeps_small_updates_single_agent():
  assert should_use_parallel_website_workflow(
    intent="website_update",
    prompt="Fix the sidebar spacing on mobile.",
  ) is False
  assert should_use_parallel_website_workflow(
    intent="website_update",
    prompt="Redesign all pages and refactor frontend routing, navigation, layout, and theme.",
  ) is True
  assert should_use_parallel_website_workflow(
    intent="website_generation",
    prompt="Build a CRM website.",
  ) is True


def test_parallel_greenfield_generation_is_disabled_by_default(monkeypatch):
  monkeypatch.delenv("ENABLE_PARALLEL_GREENFIELD_GENERATION", raising=False)
  assert parallel_greenfield_generation_enabled() is False
  monkeypatch.setenv("ENABLE_PARALLEL_GREENFIELD_GENERATION", "true")
  assert parallel_greenfield_generation_enabled() is True


def test_default_model_is_flash_while_pro_remains_opt_in():
  settings = load_settings(env={}, require_database=False)
  assert settings.gemini_model == "gemini-3.5-flash"


def test_pro_escalation_is_limited_to_flash_quality_failures(monkeypatch):
  monkeypatch.setenv("ENABLE_GEMINI_PRO_ESCALATION", "true")
  assert should_escalate_to_pro(
    "gemini-3.5-flash",
    GeminiClientError("Gemini returned invalid JSON: partial"),
  )
  assert not should_escalate_to_pro(
    "gemini-3.5-flash",
    GeminiClientError("Gemini API error 404: model not found"),
  )
  assert not should_escalate_to_pro(
    "gemini-3.1-pro-preview",
    GeminiClientError("Gemini returned invalid JSON: partial"),
  )


def test_model_history_selector_preserves_project_index_and_recent_turns():
  history = [
    {"role": "user", "parts": [{"text": "CURRENT PROJECT FILE INDEX\n- src/App.jsx"}]},
    {"role": "model", "parts": [{"text": "Acknowledged."}]},
    *[
      {
        "role": "user" if index % 2 == 0 else "model",
        "parts": [{"text": f"old-{index}-" + ("x" * 300)}],
      }
      for index in range(12)
    ],
  ]

  selected, meta = select_model_chat_history(history, max_chars=1_500)

  selected_text = "\n".join(
    str(part.get("text") or "")
    for item in selected
    for part in item.get("parts") or []
    if isinstance(part, dict)
  )
  assert meta["compacted"] is True
  assert meta["selected_chars"] <= 1_500
  assert "CURRENT PROJECT FILE INDEX" in selected_text
  assert "old-11-" in selected_text


def test_frontend_waits_for_backend_stop_before_aborting_stream():
  source = Path("src/main.jsx").read_text(encoding="utf-8")
  start = source.index("async function stopWebsiteGeneration()")
  end = source.index("function isGenerationCancelledError", start)
  stop_source = source[start:end]

  assert "/generate/status" in stop_source
  assert stop_source.index("await api") < stop_source.index("generationAbortControllerRef.current?.abort()")
  assert "setIsGenerating(false)" not in stop_source[: stop_source.index("if (!backendStopped)")]


class _FakeGeminiClient:
  model = "gemini-test"

  def __init__(self, responses):
    self.responses = list(responses)

  def _post_generate_content(self, payload):
    return self.responses.pop(0)
