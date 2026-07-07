from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import datetime, timezone

from backend.audit_logging import RunTelemetryContext, telemetry_scope
from backend.conversation_flow_logger import (
  ConversationFlowLogger,
  set_conversation_flow_logger_for_tests,
)
from backend.debug_trace import begin_backend_flow_capture, trace_print
from backend.agents.orchestration.runtime_parts.state import existing_agentic_runtime
from backend.agents.streaming.file_agent import _runtime_steps_from_tool_calls


def test_conversation_flow_logger_writes_plain_daily_log_file(tmp_path):
  logger = ConversationFlowLogger(
    root_dir=tmp_path / "logs",
    now=lambda: datetime(2026, 7, 4, 20, 10, tzinfo=timezone.utc),
  )
  context = RunTelemetryContext(
    request_id="req-9",
    user_id="user-9",
    project_id="project-9",
    agent_run_id="agent-run-9",
    generation_run_id="generation-run-9",
  )

  with telemetry_scope(context):
    logger.log(
      event_type="conversation.flow.completed",
      prompt="i want narendra modi history as pdf",
      project_id="project-9",
      chat_session_id="session-1",
      chat_topic_id="topic-1",
      topic_resolution={"topic_action": "reuse", "reason": "same_topic_followup", "confidence": 0.92},
      routing_result={"intent": "document_artifact", "next_action": "write_document_artifact", "next_tool": "generate_document_artifact", "reason": "pdf follow-up"},
      adaptive_route={"route": "conversation", "reason": "referential followup"},
      selected_files=["docs/narendra_modi_history.pdf"],
      generated_files=[{"path": "docs/narendra_modi_history.pdf"}],
      project_files=[{"path": "reports/operations_report.pdf"}],
      status="completed",
      extra={
        "effective_prompt": "Export narendra modi history as pdf",
        "backend_flow_files": [
          "backend/api/generation.py",
          "backend/api/generation_parts/preflight.py",
          "backend/agents/orchestration/runner_parts/document_artifact.py",
        ],
        "backend_flow_functions": {
          "backend/api/generation.py": ["_run_generation_pipeline_unlocked"],
          "backend/agents/orchestration/runner_parts/document_artifact.py": ["run_document_artifact_flow"],
        },
        "backend_flow_process": [
          "api.generation.request_received",
          "artifact.document_prompt_built",
          "conversation.flow.completed",
        ],
        "semantic_flow_files": ["backend/agents/orchestration/runner_parts/document_artifact.py"],
        "semantic_flow_functions": {
          "backend/agents/orchestration/runner_parts/document_artifact.py": ["run_document_artifact_flow"],
        },
        "semantic_flow_process": ["artifact.document_prompt_built"],
        "infra_flow_files": ["backend/api/generation.py"],
        "infra_flow_functions": {
          "backend/api/generation.py": ["_run_generation_pipeline_unlocked"],
        },
        "infra_flow_process": ["api.generation.request_received"],
        "runtime_tool_sequence": ["route_generation_action", "generate_document_artifact"],
        "runtime_steps": ["chief_orchestrator", "document_artifact_agent"],
        "workspace_candidate_pool": ["src/App.jsx", "src/pages/Reports.jsx"],
      },
    )

  path = tmp_path / "logs" / "teminal_testinh_2026-07-04.log"
  text = path.read_text(encoding="utf-8")
  assert "event: conversation.flow.completed" in text
  assert "prompt: i want narendra modi history as pdf" in text
  assert "intent: document_artifact" in text
  assert "selected_files:" in text
  assert "docs/narendra_modi_history.pdf" in text
  assert "project_context_files:" in text
  assert "reports/operations_report.pdf" in text
  assert "backend_flow_files:" in text
  assert "backend/api/generation.py" in text
  assert "backend_flow_functions:" in text
  assert "_run_generation_pipeline_unlocked" in text
  assert "backend_flow_process:" in text
  assert "artifact.document_prompt_built" in text
  assert "semantic_flow_files:" in text
  assert "semantic_flow_functions:" in text
  assert "infra_flow_files:" in text
  assert "infra_flow_functions:" in text
  assert "runtime_tool_sequence:" in text
  assert "generate_document_artifact" in text
  assert "runtime_steps:" in text
  assert "document_artifact_agent" in text
  assert "workspace_candidate_pool:" in text
  assert "src/pages/Reports.jsx" in text


def test_backend_flow_capture_records_real_functions_for_log(tmp_path):
  logger = ConversationFlowLogger(
    root_dir=tmp_path / "logs",
    now=lambda: datetime(2026, 7, 4, 20, 10, tzinfo=timezone.utc),
  )
  context = RunTelemetryContext(
    request_id="req-live",
    user_id="user-live",
    project_id="project-live",
    agent_run_id="agent-run-live",
    generation_run_id="generation-run-live",
  )

  set_conversation_flow_logger_for_tests(logger)
  try:
    begin_backend_flow_capture()
    trace_print("ENTER", file="/workspace/backend/api/generation.py", function="_run_generation_pipeline_unlocked", class_name="-")
    trace_print("EXIT", file="/workspace/backend/agents/orchestration/runner_parts/core.py", function="run", class_name="WorktualGenerationOrchestrator")

    module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "generation_parts" / "flow_trace.py"
    spec = importlib.util.spec_from_file_location("test_flow_trace_module", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    log_generation_flow_trace = module.log_generation_flow_trace

    with telemetry_scope(context):
      log_generation_flow_trace(
        "conversation.flow.completed",
        prompt="hi",
        project_id="project-live",
        routing_result={"intent": "greeting", "next_tool": "handle_greeting"},
        adaptive_route={"route": "tiny_chat", "reason": "greeting"},
        status="completed",
      )
  finally:
    set_conversation_flow_logger_for_tests(None)

  text = (tmp_path / "logs" / "teminal_testinh_2026-07-04.log").read_text(encoding="utf-8")
  assert "backend/api/generation.py" in text
  assert "_run_generation_pipeline_unlocked" in text
  assert "WorktualGenerationOrchestrator.run" in text
  assert "exit.run" in text


def test_greeting_flow_trace_filters_generation_noise():
  module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "generation_parts" / "flow_trace.py"
  spec = importlib.util.spec_from_file_location("test_flow_trace_module_filtered", module_path)
  assert spec and spec.loader
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)

  normalized = module._normalize_runtime_capture(
    {
      "files": [
        "/workspace/backend/api/generation.py",
        "/workspace/backend/agents/orchestration/conversation_parts/response.py",
      ],
      "functions_by_file": {
        "/workspace/backend/api/generation.py": ["generate_website", "record_project_chat_message"],
        "/workspace/backend/agents/orchestration/conversation_parts/response.py": [
          "generate_conversation_response",
          "ConversationTool.handle_greeting",
        ],
      },
      "process": [
        "enter.generate_website",
        "exit.generate_website",
        "enter.record_project_chat_message",
        "exit.record_project_chat_message",
        "enter.generate_conversation_response",
        "exit.handle_greeting",
      ],
    },
    event_type="conversation.flow.completed",
    intent="greeting",
    adaptive_route_name="tiny_chat",
  )

  assert normalized["files"] == ["/workspace/backend/agents/orchestration/conversation_parts/response.py"]
  assert normalized["functions_by_file"]["/workspace/backend/agents/orchestration/conversation_parts/response.py"] == [
    "generate_conversation_response",
    "ConversationTool.handle_greeting",
  ]
  assert normalized["semantic_files"] == ["/workspace/backend/agents/orchestration/conversation_parts/response.py"]
  assert normalized["infra_files"] == []
  assert "exit.handle_greeting" in normalized["semantic_process"]
  assert "enter.generate_website" not in normalized["process"]
  assert "exit.record_project_chat_message" not in normalized["process"]


def test_greeting_preflight_uses_semantic_fallback_when_runtime_capture_is_only_infra():
  module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "generation_parts" / "flow_trace.py"
  spec = importlib.util.spec_from_file_location("test_flow_trace_module_preflight", module_path)
  assert spec and spec.loader
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)

  normalized = module._normalize_runtime_capture(
    {
      "files": [
        "/workspace/backend/api/generation.py",
        "/workspace/backend/agents/gemini_client/client.py",
      ],
      "functions_by_file": {
        "/workspace/backend/api/generation.py": ["project_load", "GeminiProvider.__init__"],
        "/workspace/backend/agents/gemini_client/client.py": ["GeminiClient.build_generate_json_payload"],
      },
      "process": [
        "enter.project_load",
        "exit.project_load",
        "exit.__init__",
      ],
    },
    event_type="conversation.flow.preflight",
    intent="",
    adaptive_route_name="tiny_chat",
  )

  assert normalized["files"] == []
  assert normalized["functions_by_file"] == {}
  assert normalized["process"] == []


def test_tiny_chat_preflight_fallback_is_minimal_and_repo_relative():
  module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "generation_parts" / "flow_trace.py"
  spec = importlib.util.spec_from_file_location("test_flow_trace_module_fallback", module_path)
  assert spec and spec.loader
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)

  files = module._backend_flow_files_for_event(
    event_type="conversation.flow.preflight",
    adaptive_route={"route": "tiny_chat"},
  )
  functions = module._backend_flow_functions_for_event(
    event_type="conversation.flow.preflight",
    adaptive_route={"route": "tiny_chat"},
  )
  process = module._backend_flow_process_for_event(
    event_type="conversation.flow.preflight",
    adaptive_route={"route": "tiny_chat"},
  )

  assert files == [
    "backend/api/generation_parts/preflight.py",
    "backend/agents/request_complexity.py",
    "backend/agents/memory/topic_clustering.py",
  ]
  assert list(functions) == [
    "backend/agents/request_complexity.py",
    "backend/agents/memory/topic_clustering.py",
    "backend/api/generation_parts/preflight.py",
  ]
  assert process == [
    "api.generation.request_received",
    "memory.topic.resolve_chat_topic",
    "adaptive_route.tiny_chat",
    "conversation.flow.preflight_logged",
  ]


def test_existing_agentic_runtime_accepts_tool_source_of_truth_with_tool_calls_only():
  runtime = existing_agentic_runtime(
    {
      "multi_agent_system": {
        "agentic_runtime": {
          "tool_source_of_truth": True,
          "tool_calls": [{"name": "analyze_update_request"}, {"name": "str_replace"}],
          "status": "completed",
        }
      }
    }
  )
  assert runtime is not None


def test_streaming_runtime_derives_update_steps_from_tool_calls():
  steps = _runtime_steps_from_tool_calls(
    [{"name": "read_file"}, {"name": "str_replace"}, {"name": "WRITE_PROJECT_FILES"}],
    intent="website_update",
  )
  assert steps[0]["agent"] == "update_analysis_agent"
  assert steps[0]["tool"] == "analyze_update_request"
  assert any(step["tool"] == "str_replace" for step in steps)
