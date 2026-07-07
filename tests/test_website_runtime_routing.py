from __future__ import annotations

from types import SimpleNamespace


from backend.agents.agent_runtime.errors import AgentRuntimeLoopError
from backend.agents.orchestration.runner_parts import website_runtime as website_runtime_module


class _Store:
  def list_files(self, *_args, **_kwargs):
    return [{"path": "src/App.jsx", "content": "export default function App(){ return null; }"}]


def _orchestrator():
  events: list[tuple[str, str]] = []
  orchestrator = SimpleNamespace(
    project_id="project-1",
    tool_context=SimpleNamespace(store=_Store()),
    user=SimpleNamespace(id="user-1"),
    _emit_progress=lambda step, message, **_kwargs: events.append((step, message)),
    chat_session_id="chat-1",
    agent_run_id="agent-1",
    project_name="Demo",
    patch_action=None,
    graph_thread_id=None,
    resume_graph=False,
  )
  return orchestrator, events


def _state(route: str):
  return SimpleNamespace(
    intent="website_update",
    adaptive_route={"route": route},
    user_prompt="change the entire website theme and color to red and white",
    artifact_client=None,
    control_client=None,
    attachments=[],
    routing_result={},
    prepared_sections=[],
    confirmation_brief=None,
  )


def test_large_project_update_does_not_force_streaming_single_agent(monkeypatch):
  orchestrator, _events = _orchestrator()
  state = _state("large_project")

  monkeypatch.setattr(website_runtime_module, "unified_website_updates_active", lambda: True)
  monkeypatch.setattr(website_runtime_module, "streaming_file_agent_enabled", lambda: True)
  monkeypatch.setattr(website_runtime_module, "parallel_stream_orchestrator_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "parallel_website_generation_default", lambda: False)
  monkeypatch.setattr(website_runtime_module, "langgraph_website_runtime_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "streaming_fast_path_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "is_error_repair_prompt", lambda _prompt: False)
  monkeypatch.setattr(website_runtime_module, "ensure_update_visual_baseline", lambda **_kwargs: None)
  monkeypatch.setattr(website_runtime_module, "run_streaming_file_agent", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("streaming agent should not run for large project route")))

  captured: dict[str, str] = {}

  def fake_execute_real_agent_runtime_loop(**kwargs):
    captured["prompt"] = kwargs["prompt"]
    return {"runtime": {"workflow": "real_agent_runtime"}, "generated_website": {"files": []}}

  monkeypatch.setattr(website_runtime_module, "execute_real_agent_runtime_loop", fake_execute_real_agent_runtime_loop)
  monkeypatch.setattr(
    website_runtime_module,
    "finalize_runtime_generated_website",
    lambda _orchestrator, _state, runtime_result, **_kwargs: {"ok": True, "runtime_result": runtime_result},
  )

  result = website_runtime_module.handle_website_runtime_branch(orchestrator, state)

  assert result["ok"] is True
  assert captured["prompt"] == state.user_prompt


def test_large_project_update_uses_parallel_orchestrator_when_enabled(monkeypatch):
  orchestrator, _events = _orchestrator()
  state = _state("large_project")

  monkeypatch.setattr(website_runtime_module, "unified_website_updates_active", lambda: True)
  monkeypatch.setattr(website_runtime_module, "streaming_file_agent_enabled", lambda: True)
  monkeypatch.setattr(website_runtime_module, "parallel_stream_orchestrator_enabled", lambda: True)
  monkeypatch.setattr(website_runtime_module, "parallel_website_generation_default", lambda: True)
  monkeypatch.setattr(website_runtime_module, "should_use_parallel_website_workflow", lambda **_kwargs: True)
  monkeypatch.setattr(website_runtime_module, "langgraph_website_runtime_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "streaming_fast_path_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "is_error_repair_prompt", lambda _prompt: False)
  monkeypatch.setattr(website_runtime_module, "ensure_update_visual_baseline", lambda **_kwargs: None)
  monkeypatch.setattr(website_runtime_module, "run_streaming_file_agent", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("streaming agent should not run when parallel orchestrator is enabled for large project route")))

  captured: dict[str, str] = {}

  def fake_parallel_runtime(**kwargs):
    captured["prompt"] = kwargs["prompt"]
    return {"runtime": {"workflow": "parallel_stream_orchestrator"}, "generated_website": {"files": []}}

  monkeypatch.setattr(website_runtime_module, "run_parallel_stream_orchestrator", fake_parallel_runtime)
  monkeypatch.setattr(
    website_runtime_module,
    "finalize_runtime_generated_website",
    lambda _orchestrator, _state, runtime_result, **_kwargs: {"ok": True, "runtime_result": runtime_result},
  )

  result = website_runtime_module.handle_website_runtime_branch(orchestrator, state)

  assert result["ok"] is True
  assert captured["prompt"] == state.user_prompt


def test_targeted_update_uses_streaming_file_agent_when_enabled(monkeypatch):
  orchestrator, _events = _orchestrator()
  state = _state("targeted_update")

  monkeypatch.setattr(website_runtime_module, "unified_website_updates_active", lambda: True)
  monkeypatch.setattr(website_runtime_module, "streaming_file_agent_enabled", lambda: True)
  monkeypatch.setattr(website_runtime_module, "parallel_stream_orchestrator_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "parallel_website_generation_default", lambda: False)
  monkeypatch.setattr(website_runtime_module, "langgraph_website_runtime_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "streaming_fast_path_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "is_error_repair_prompt", lambda _prompt: False)
  monkeypatch.setattr(website_runtime_module, "ensure_update_visual_baseline", lambda **_kwargs: None)
  monkeypatch.setattr(website_runtime_module, "execute_real_agent_runtime_loop", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("persistent runtime should not run for targeted streaming update")))

  def fake_streaming_runtime(**kwargs):
    return {
      "runtime": {"workflow": "streaming_file_agent", "status": "completed"},
      "generated_website": {"files": [{"path": "src/App.jsx", "code": "export default function App(){ return null; }"}]},
    }

  monkeypatch.setattr(website_runtime_module, "run_streaming_file_agent", fake_streaming_runtime)
  monkeypatch.setattr(
    website_runtime_module,
    "finalize_runtime_generated_website",
    lambda _orchestrator, _state, runtime_result, **_kwargs: {"ok": True, "runtime_result": runtime_result},
  )

  result = website_runtime_module.handle_website_runtime_branch(orchestrator, state)

  assert result["ok"] is True
  assert result["runtime_result"]["runtime"]["workflow"] == "streaming_file_agent"


def test_persistent_update_failure_returns_failed_runtime_payload(monkeypatch):
  orchestrator, _events = _orchestrator()
  state = _state("targeted_update")

  monkeypatch.setattr(website_runtime_module, "unified_website_updates_active", lambda: True)
  monkeypatch.setattr(website_runtime_module, "streaming_file_agent_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "parallel_stream_orchestrator_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "parallel_website_generation_default", lambda: False)
  monkeypatch.setattr(website_runtime_module, "langgraph_website_runtime_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "streaming_fast_path_enabled", lambda: False)
  monkeypatch.setattr(website_runtime_module, "is_error_repair_prompt", lambda _prompt: False)
  monkeypatch.setattr(website_runtime_module, "ensure_update_visual_baseline", lambda **_kwargs: None)

  def fail_runtime(**_kwargs):
    raise AgentRuntimeLoopError("Scoped update produced zero changed files.")

  monkeypatch.setattr(website_runtime_module, "execute_real_agent_runtime_loop", fail_runtime)
  monkeypatch.setattr(
    website_runtime_module,
    "finalize_runtime_generated_website",
    lambda _orchestrator, _state, runtime_result, **_kwargs: {"ok": True, "runtime_result": runtime_result},
  )

  result = website_runtime_module.handle_website_runtime_branch(orchestrator, state)

  runtime = result["runtime_result"]["runtime"]
  assert runtime["status"] == "failed"
  assert runtime["branch"] == "website_update"
  assert runtime["operation"] == "website_update"
  assert runtime["source"] == "failed_update_runtime"
  assert runtime["no_code_changes"] is True
  assert "zero changed files" in runtime["output_text"]
  assert result["runtime_result"]["generated_website"]["files"] == []
