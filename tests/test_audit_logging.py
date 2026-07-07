import json
from datetime import datetime, timezone

from backend.audit_logging import (
  DYNAMIC_AGENT_LOG_NAME,
  FLOW_TRACE_LOG_NAME,
  QUERY_LOG_NAME,
  RunTelemetryContext,
  StructuredAuditLogger,
  configure_audit_logger,
  log_flow_event,
  log_query_event,
  set_audit_logger_for_tests,
  telemetry_scope,
)


def read_jsonl(path):
  return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_audit_logger_creates_two_daily_streams_without_deleting_old_folders(tmp_path):
  old_folder = tmp_path / "2026-05-01"
  old_folder.mkdir()
  marker = old_folder / "keep.txt"
  marker.write_text("keep", encoding="utf-8")
  logger = StructuredAuditLogger(
    root_dir=tmp_path,
    now=lambda: datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
  )
  context = RunTelemetryContext.create(
    request_id="request-1",
    user_id="user-1",
    project_id="project-1",
  )

  with telemetry_scope(context):
    logger.log_query_event("query.received", payload={"prompt": "Build a CRM"})
    logger.log_dynamic_agent_event("agent.created", payload={"agent_id": "crm_pipeline_agent"})
    logger.log_flow_event("conversation.flow.completed", payload={"prompt": "Build a CRM", "selected_files": ["src/App.jsx"]})

  daily_folder = tmp_path / "2026-06-04"
  assert sorted(path.name for path in daily_folder.iterdir()) == sorted([DYNAMIC_AGENT_LOG_NAME, FLOW_TRACE_LOG_NAME, QUERY_LOG_NAME])
  assert marker.read_text(encoding="utf-8") == "keep"
  query_event = read_jsonl(daily_folder / QUERY_LOG_NAME)[0]
  assert query_event["request_id"] == "request-1"
  assert query_event["user_id"] == "user-1"
  assert query_event["project_id"] == "project-1"


def test_configure_audit_logger_writes_flow_trace_stream(tmp_path):
  try:
    configure_audit_logger(root_dir=tmp_path / "configured_logs", content_max_chars=100)
    log_flow_event("conversation.flow.preflight", payload={"prompt": "Give me APJ history as pdf", "selected_files": ["docs/history.md"]})

    daily_folder = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    event = read_jsonl(tmp_path / "configured_logs" / daily_folder / FLOW_TRACE_LOG_NAME)[0]
    assert event["event_type"] == "conversation.flow.preflight"
    assert event["payload"]["selected_files"] == ["docs/history.md"]
  finally:
    set_audit_logger_for_tests(None)


def test_audit_logger_redacts_secrets_and_never_writes_code_bodies(tmp_path):
  logger = StructuredAuditLogger(
    root_dir=tmp_path,
    content_max_chars=20,
    now=lambda: datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
  )
  source_code = "export default function SecretApp() { return <main>hidden code</main>; }"

  logger.log_query_event(
    "tool.completed",
    payload={
      "authorization": "Bearer secret-token",
      "input_tokens": 123,
      "output_tokens": 456,
      "message": "api_key=super-secret build a private dashboard with all details",
      "files": [{"path": "src/App.jsx", "code": source_code}],
      "candidate_changes": [{"path": "src/Panel.jsx", "content": source_code}],
    },
  )

  event_text = (tmp_path / "2026-06-04" / QUERY_LOG_NAME).read_text(encoding="utf-8")
  event = json.loads(event_text)
  assert "super-secret" not in event_text
  assert source_code not in event_text
  assert event["payload"]["authorization"] == "[REDACTED]"
  assert event["payload"]["input_tokens"] == 123
  assert event["payload"]["output_tokens"] == 456
  assert event["payload"]["message"]["truncated"] is True
  assert event["payload"]["files"][0]["path"] == "src/App.jsx"
  assert event["payload"]["files"][0]["char_count"] == len(source_code)
  assert len(event["payload"]["files"][0]["sha256"]) == 64


def test_dynamic_candidate_event_never_writes_candidate_body(tmp_path):
  logger = StructuredAuditLogger(
    root_dir=tmp_path,
    now=lambda: datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
  )
  source_code = "export default function App() { return <main>private candidate</main>; }"

  logger.log_dynamic_agent_event(
    "candidate_change.accepted",
    payload={"path": "src/App.jsx", "content": source_code, "agent_id": "ui-agent"},
  )

  event_text = (tmp_path / "2026-06-04" / DYNAMIC_AGENT_LOG_NAME).read_text(encoding="utf-8")
  event = json.loads(event_text)
  assert source_code not in event_text
  assert event["payload"]["path"] == "src/App.jsx"
  assert event["payload"]["char_count"] == len(source_code)
  assert event["payload"]["code_redacted"] is True


def test_configure_audit_logger_sets_global_daily_stream_path(tmp_path):
  try:
    configure_audit_logger(root_dir=tmp_path / "configured_logs", content_max_chars=100)
    log_query_event("query.received", payload={"prompt": "Build a booking site"})

    daily_folder = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    event = read_jsonl(tmp_path / "configured_logs" / daily_folder / QUERY_LOG_NAME)[0]
    assert event["event_type"] == "query.received"
    assert event["payload"]["prompt"]["preview"] == "Build a booking site"
  finally:
    set_audit_logger_for_tests(None)
