from backend.agents.streaming.streaming_visual_qa import (
  post_update_visual_qa_enabled,
  run_precommit_automation_gate,
  run_post_update_visual_qa,
)
from backend.storage import UserContext


def test_post_update_visual_qa_skips_when_disabled(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_POST_UPDATE_VISUAL_QA", "false")
  events: list[tuple[str, str]] = []

  def emit(step: str, message: str, **_kwargs) -> None:
    events.append((step, message))

  result = run_post_update_visual_qa(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="user"),
    tool_context=object(),
    build_gate_result={"status": "ready", "preview_url": "/preview/"},
    emit_progress=emit,
  )

  assert result is None
  assert events == []


def test_post_update_visual_qa_skips_when_build_not_ready(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_POST_UPDATE_VISUAL_QA", "true")
  events: list[str] = []

  result = run_post_update_visual_qa(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="user"),
    tool_context=object(),
    build_gate_result={"status": "failed", "build_log": "error"},
    emit_progress=lambda step, _message, **_kwargs: events.append(step),
  )

  assert result is None
  assert events == []


def test_post_update_visual_qa_emits_passed_event(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_POST_UPDATE_VISUAL_QA", "true")
  events: list[str] = []

  def fake_tool(_context, _user, _arguments):
    return {"status": "passed", "mode": "backend_preview_integrity", "browser_rendered": False, "warnings": []}

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.run_preview_visual_qa_tool",
    fake_tool,
  )

  result = run_post_update_visual_qa(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="user"),
    tool_context=object(),
    build_gate_result={"status": "ready", "preview_url": "/preview/", "build_log": "built"},
    emit_progress=lambda step, _message, **_kwargs: events.append(step),
  )

  assert result is not None
  assert result["status"] == "passed"
  assert "gate.visual_qa.running" in events
  assert "gate.visual_qa.passed" in events


def test_post_update_visual_qa_emits_failed_event_with_structured_detail(monkeypatch) -> None:
  monkeypatch.setenv("ENABLE_POST_UPDATE_VISUAL_QA", "true")
  captured: list[dict[str, object]] = []

  def fake_tool(_context, _user, _arguments):
    return {"status": "failed", "warnings": ["Missing hero section"]}

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.run_preview_visual_qa_tool",
    fake_tool,
  )

  result = run_post_update_visual_qa(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="user"),
    tool_context=object(),
    build_gate_result={"status": "ready", "preview_url": "/preview/", "build_log": "built"},
    emit_progress=lambda step, _message, **kwargs: captured.append({"step": step, **kwargs}),
  )

  assert result is not None
  assert result["status"] == "failed"
  failed = next(item for item in captured if item["step"] == "gate.visual_qa.failed")
  detail = failed["detail"]
  assert detail["category"] == "visual_qa"
  assert detail["code"] == "visual_qa_failed"
  assert detail["suggested_actions"]


def test_post_update_visual_qa_enabled_default(monkeypatch) -> None:
  monkeypatch.delenv("ENABLE_POST_UPDATE_VISUAL_QA", raising=False)
  assert post_update_visual_qa_enabled() is True


def test_precommit_automation_gate_builds_candidate_and_passes_targeted_scope(monkeypatch) -> None:
  captured = {}

  def fake_build(_context, _user, arguments):
    captured["files"] = arguments["files"]
    return {
      "version": {
        "id": "version-1",
        "status": "ready",
        "preview_url": "/preview/",
        "build_log": "built",
      }
    }

  def fake_visual(_context, _user, arguments):
    captured["visual_arguments"] = arguments
    return {"status": "passed", "automation_test": {"test_run_id": "test-1"}}

  monkeypatch.setattr("backend.agentic.tools.handlers.build_staged_project_preview_tool", fake_build)
  monkeypatch.setattr("backend.agentic.tools.handlers.run_preview_visual_qa_tool", fake_visual)

  build_result, visual_result = run_precommit_automation_gate(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="owner"),
    tool_context=object(),
    candidate_files=[{"path": "src/pages/Dashboard.jsx", "content": "export default function Dashboard(){}"}],
    changed_paths=["src/pages/Dashboard.jsx"],
    operation="update",
    prompt="Update dashboard",
    chat_session_id="session-1",
    agent_run_id="agent-1",
    emit_progress=lambda *_args, **_kwargs: None,
  )

  assert build_result["status"] == "ready"
  assert visual_result["status"] == "passed"
  assert captured["visual_arguments"]["operation"] == "update"
  assert captured["visual_arguments"]["chat_session_id"] == "session-1"
  assert "src/pages/Dashboard.jsx" in captured["visual_arguments"]["changed_paths"]
  assert build_result["normalization_paths"]


def test_precommit_automation_gate_normalizes_module_contract_before_build(monkeypatch) -> None:
  captured = {}

  def fake_build(_context, _user, arguments):
    captured["files"] = arguments["files"]
    return {
      "version": {
        "id": "version-1",
        "status": "ready",
        "preview_url": "/preview/",
        "build_log": "built",
      }
    }

  def fake_visual(_context, _user, arguments):
    captured["visual_arguments"] = arguments
    return {"status": "passed", "automation_test": {"test_run_id": "test-1"}}

  monkeypatch.setattr("backend.agentic.tools.handlers.build_staged_project_preview_tool", fake_build)
  monkeypatch.setattr("backend.agentic.tools.handlers.run_preview_visual_qa_tool", fake_visual)

  build_result, visual_result = run_precommit_automation_gate(
    project_id="project-1",
    user=UserContext(id="user-1", email="u@example.com", role="owner"),
    tool_context=object(),
    candidate_files=[
      {"path": "src/App.jsx", "content": 'import { AiChat } from "./pages/AiChat";\nexport default AiChat;'},
      {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }"},
    ],
    changed_paths=["src/App.jsx"],
    operation="update",
    prompt="Fix preview import error",
    chat_session_id="session-1",
    agent_run_id="agent-1",
    emit_progress=lambda *_args, **_kwargs: None,
  )
  app = next(item for item in captured["files"] if item["path"] == "src/App.jsx")

  assert build_result["status"] == "ready"
  assert visual_result["status"] == "passed"
  assert 'import AiChat from "./pages/AiChat";' in app["content"]
  assert "src/App.jsx" in build_result["normalization_paths"]
