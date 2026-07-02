from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.audit_logging import RunTelemetryContext, telemetry_scope
from backend.gemini_token_usage_logger import GeminiTokenUsageLogger, set_gemini_token_usage_logger_for_tests
from backend.llm.gemini_client import log_token_usage
from backend.usage.recorder import bind_usage_store


def read_single_event(path):
  return json.loads(path.read_text(encoding="utf-8").strip())


def test_gemini_token_usage_logger_writes_daily_query_scoped_file(tmp_path):
  logger = GeminiTokenUsageLogger(
    root_dir=tmp_path / "gemini_token_usage",
    now=lambda: datetime(2026, 6, 5, 10, 30, tzinfo=timezone.utc),
  )
  context = RunTelemetryContext(
    request_id="req-1",
    user_id="user-1",
    project_id="project-1",
    agent_run_id="agent-run-1",
    generation_run_id="generation-run-1",
  )

  with telemetry_scope(context):
    logger.log(
      {
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
        "call": "generate_website_artifact",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "thought_tokens": 12,
        "cached_tokens": 3,
        "prompt_chars": 1200,
        "output_chars": 800,
      },
      duration_ms=1234.567,
    )

  event = read_single_event(tmp_path / "gemini_token_usage" / "2026-06-05_token_usage.log")
  assert event["request_id"] == "req-1"
  assert event["agent_run_id"] == "agent-run-1"
  assert event["generation_run_id"] == "generation-run-1"
  assert event["user_id"] == "user-1"
  assert event["project_id"] == "project-1"
  assert event["provider"] == "gemini"
  assert event["model"] == "gemini-3.1-pro-preview"
  assert event["call"] == "generate_website_artifact"
  assert event["input_tokens"] == 100
  assert event["output_tokens"] == 50
  assert event["total_tokens"] == 150
  assert event["thought_tokens"] == 12
  assert event["cached_tokens"] == 3
  assert event["prompt_chars"] == 1200
  assert event["output_chars"] == 800
  assert event["duration_ms"] == 1234.57


def test_gemini_client_log_token_usage_writes_dedicated_usage_file(tmp_path):
  logger = GeminiTokenUsageLogger(
    root_dir=tmp_path / "tokens",
    now=lambda: datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
  )
  set_gemini_token_usage_logger_for_tests(logger)

  context = RunTelemetryContext(
    request_id="req-2",
    user_id="user-2",
    project_id="project-2",
    generation_run_id="generation-run-2",
  )
  with telemetry_scope(context):
    log_token_usage(
      {
        "usageMetadata": {
          "promptTokenCount": 10,
          "candidatesTokenCount": 20,
          "totalTokenCount": 30,
          "thoughtsTokenCount": 4,
          "cachedContentTokenCount": 2,
        }
      },
      model="gemini-test",
      trace_label="route_generation_action",
      prompt_chars=111,
      output_chars=222,
      duration_ms=12,
      system_instruction_chars=40,
      chat_history_chars=60,
      prompt_fragments_used=["user_prompt", "system_instruction", "chat_history"],
      selected_files=["src/App.jsx"],
      memory_items_used=2,
    )

  event = read_single_event(tmp_path / "tokens" / "2026-06-05_token_usage.log")
  assert event["request_id"] == "req-2"
  assert event["project_id"] == "project-2"
  assert event["generation_run_id"] == "generation-run-2"
  assert event["model"] == "gemini-test"
  assert event["call"] == "route_generation_action"
  assert event["input_tokens"] == 10
  assert event["output_tokens"] == 20
  assert event["total_tokens"] == 30
  assert event["thought_tokens"] == 4
  assert event["cached_tokens"] == 2
  assert event["cached_input_tokens"] == 2
  assert event["estimated_cost_usd"] > 0
  assert event["estimated_credits"] > 0
  assert event["pricing_version"]
  assert event["execution_stage"] == "routing"
  assert event["model_role"] == "control"
  assert event["thinking_level"] == "minimal"
  assert event["context_chars"] == 211
  assert event["input_chars"] == 211
  assert event["system_instruction_chars"] == 40
  assert event["chat_history_chars"] == 60
  assert event["prompt_fragments_used"] == ["user_prompt", "system_instruction", "chat_history"]
  assert event["selected_files"] == ["src/App.jsx"]
  assert event["memory_items_used"] == 2
  assert event["prompt_chars"] == 111
  assert event["output_chars"] == 222
  assert event["duration_ms"] == 12.0


def test_gemini_token_usage_recorder_persists_input_output_breakdown(tmp_path):
  class FakeUsageStore:
    def __init__(self):
      self.events = []
      self.counter_updates = []

    def record_user_token_usage_event(self, user_id, **kwargs):
      self.events.append({"user_id": user_id, **kwargs})
      return {"id": "event-1"}

    def record_user_token_usage(self, user_id, tokens):
      self.counter_updates.append({"user_id": user_id, "tokens": tokens})

  logger = GeminiTokenUsageLogger(
    root_dir=tmp_path / "tokens",
    now=lambda: datetime(2026, 6, 5, 13, 0, tzinfo=timezone.utc),
  )
  set_gemini_token_usage_logger_for_tests(logger)
  store = FakeUsageStore()
  bind_usage_store(store)

  try:
    context = RunTelemetryContext(
      request_id="req-3",
      user_id="user-3",
      project_id="project-3",
      generation_run_id="generation-run-3",
      agent_run_id="agent-run-3",
    )
    with telemetry_scope(context):
      log_token_usage(
        {
          "usageMetadata": {
            "promptTokenCount": 123,
            "candidatesTokenCount": 45,
            "totalTokenCount": 168,
          }
        },
        model="gemini-test",
        trace_label="generate_simple_code_file",
        prompt_chars=900,
        output_chars=300,
        duration_ms=34,
      )
  finally:
    bind_usage_store(None)

  assert store.counter_updates == [{"user_id": "user-3", "tokens": 168}]
  assert len(store.events) == 1
  event = store.events[0]
  assert event["user_id"] == "user-3"
  assert event["project_id"] == "project-3"
  assert event["request_id"] == "req-3"
  assert event["generation_run_id"] == "generation-run-3"
  assert event["agent_run_id"] == "agent-run-3"
  assert event["call"] == "generate_simple_code_file"
  assert event["input_tokens"] == 123
  assert event["output_tokens"] == 45
  assert event["total_tokens"] == 168
  assert event["estimated_cost_usd"] > 0
  assert event["estimated_credits"] > 0
  assert event["execution_stage"] == "artifact"
  assert event["model_role"] == "artifact"
  assert event["thinking_level"] == "low"
  assert event["metadata"]["prompt_fragments_used"] == ["user_prompt"]
  assert event["metadata"]["input_chars"] == 900
  assert "prompt" not in event
