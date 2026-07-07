from types import SimpleNamespace

from backend.agents.agent_runtime.update_analysis import normalize_update_analysis, targeted_update_request_from_analysis
from backend.agents.runtime_config import streaming_path_parity_enabled
from backend.agents.streaming.streaming_parity import (
  clarification_stream_result,
  streaming_patch_approval_gate,
  try_deterministic_module_contract_fix_streaming,
  try_deterministic_scoped_patch_streaming,
  try_deterministic_undefined_reference_fix_streaming,
)
from tests.test_patch_approval import MemoryStoreStub


class FileStoreStub:
  def __init__(self, files: list[dict[str, str]]):
    self._files = list(files)

  def list_files(self, project_id: str, user) -> list[dict[str, str]]:
    _ = project_id, user
    return list(self._files)


class VersionedFileStoreStub(FileStoreStub):
  def create_version(self, *args, **kwargs):
    _ = args, kwargs
    return {"id": "version-1"}


def test_streaming_path_parity_enabled_defaults_true(monkeypatch):
  monkeypatch.delenv("ENABLE_STREAMING_PATH_PARITY", raising=False)
  monkeypatch.setenv("AGENTIC_PARITY_TARGET", "48")
  assert streaming_path_parity_enabled() is True


def test_clarification_stream_result_shape():
  result = clarification_stream_result("Which page should change?")
  assert result["runtime"]["status"] == "needs_clarification"
  assert result["runtime"]["clarification_question"] == "Which page should change?"


def test_streaming_patch_approval_gate_pauses_before_commit(monkeypatch):
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "true")
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  store = MemoryStoreStub()
  tool_context = SimpleNamespace(store=store, settings=SimpleNamespace())
  user = SimpleNamespace(id="user-1")
  events: list[dict] = []

  result = streaming_patch_approval_gate(
    tool_context=tool_context,
    user=user,
    project_id="project-1",
    prompt="Update hero headline",
    write_payload=[{"path": "src/App.jsx", "content": "export default function App(){ return 1; }"}],
    files_before_map={"src/App.jsx": "export default function App(){ return 0; }"},
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, **kwargs}),
    patch_action=None,
    summary="Proposed hero update",
  )

  assert result is not None
  assert result["awaiting_patch_approval"] is True
  assert result["runtime"]["status"] == "awaiting_patch_approval"
  assert any(event["step"] == "patch.approval.required" for event in events)
  assert store.items


def test_streaming_patch_approval_gate_skipped_when_parity_disabled(monkeypatch):
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "true")
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "false")
  store = MemoryStoreStub()
  tool_context = SimpleNamespace(store=store, settings=SimpleNamespace())

  result = streaming_patch_approval_gate(
    tool_context=tool_context,
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    prompt="Update hero headline",
    write_payload=[{"path": "src/App.jsx", "content": "updated"}],
    files_before_map={"src/App.jsx": "original"},
    emit_progress=lambda *_args, **_kwargs: None,
    patch_action=None,
  )

  assert result is None
  assert not store.items


def test_try_deterministic_scoped_patch_streaming_applies_targeted_update(monkeypatch):
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_POST_UPDATE_BUILD_GATE", "false")

  analysis = normalize_update_analysis(
    {
      "update_mode": "targeted_patch",
      "request_kind": "brand_name_update",
      "execution_strategy": "deterministic_patch",
      "scope": "small",
      "summary": "Change the website brand name.",
      "candidate_files": ["index.html", "src/App.jsx"],
      "targeted_patch": {"kind": "brand_name_update", "new_value": "Worktual CRM"},
      "allow_full_regeneration": False,
    },
    existing_paths=["index.html", "src/App.jsx"],
    code_search_matches=[],
    user_prompt="change the website name to Worktual CRM",
  )
  assert targeted_update_request_from_analysis(analysis) is not None

  upsert_calls: list[dict] = []

  def fake_upsert(_tool_context, _user, payload):
    upsert_calls.append(payload)
    return {}

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.upsert_project_files_tool",
    fake_upsert,
  )

  files = [
    {"path": "index.html", "content": "<title>ApexCRM</title>"},
    {"path": "src/App.jsx", "content": "export default function App() { return <h1>ApexCRM</h1>; }"},
  ]
  tool_context = SimpleNamespace(store=FileStoreStub(files), settings=SimpleNamespace())
  events: list[dict] = []

  result = try_deterministic_scoped_patch_streaming(
    update_analysis=analysis,
    tool_context=tool_context,
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    prompt="change the website name to Worktual CRM",
    intent="website_update",
    artifact_provider=SimpleNamespace(),
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, **kwargs}),
    patch_action=None,
  )

  assert result is not None
  assert result["runtime"]["engine"] == "deterministic_scoped_patch"
  assert result["runtime"]["changed_paths"] == ["index.html", "src/App.jsx"]
  assert upsert_calls
  by_path = {item["path"]: item["content"] for item in upsert_calls[0]["files"]}
  assert "<title>Worktual CRM</title>" in by_path["index.html"]
  assert "<h1>Worktual CRM</h1>" in by_path["src/App.jsx"]
  assert any(event["step"] == "agent.decision" for event in events)


def test_deterministic_module_contract_fix_is_tool_source_of_truth(monkeypatch):
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  upsert_calls: list[dict] = []
  local_sync = {"direction": "push", "path": "/tmp/demo", "count": 1}

  def fake_upsert(_tool_context, _user, payload):
    upsert_calls.append(payload)
    return {"project_id": payload["project_id"], "file_count": len(payload["files"]), "local_sync": local_sync}

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.upsert_project_files_tool",
    fake_upsert,
  )

  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import { AiChat } from "./pages/AiChat";\n'
        'import { Layout } from "./components/Layout";\n'
        "export default function App(){ return <Layout><AiChat /></Layout>; }\n"
      ),
    },
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }\n"},
    {"path": "src/components/Layout.jsx", "content": "export default function Layout({children}){ return children; }\n"},
  ]
  tool_context = SimpleNamespace(store=FileStoreStub(files), settings=SimpleNamespace())
  events: list[dict] = []

  result = try_deterministic_module_contract_fix_streaming(
    prompt="fix import error",
    tool_context=tool_context,
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
  )

  assert result is not None
  runtime = result["runtime"]
  assert runtime["engine"] == "deterministic_module_contract_fix"
  assert runtime["tool_source_of_truth"] is True
  assert runtime["local_sync"] == local_sync
  assert runtime["final_output"]["preview_status"] == "built"
  assert runtime["changed_paths"] == ["src/App.jsx"]
  assert upsert_calls
  app_patch = upsert_calls[0]["files"][0]["content"]
  assert 'import AiChat from "./pages/AiChat";' in app_patch
  assert 'import Layout from "./components/Layout";' in app_patch
  assert any(event["step"] == "files.persisted" for event in events)


def test_deterministic_module_contract_fix_persists_when_visual_qa_fails(monkeypatch):
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  upsert_calls: list[dict] = []

  def fake_upsert(_tool_context, _user, payload):
    upsert_calls.append(payload)
    return {"project_id": payload["project_id"], "file_count": len(payload["files"])}

  def fake_precommit_gate(**kwargs):
    candidate_files = kwargs["candidate_files"]
    return (
      {"status": "ready", "candidate_files": candidate_files, "preview_url": "http://preview.local"},
      {"status": "failed", "issues": [{"severity": "medium", "message": "Card spacing mismatch"}]},
    )

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.upsert_project_files_tool",
    fake_upsert,
  )
  monkeypatch.setattr(
    "backend.agents.streaming.streaming_visual_qa.run_precommit_automation_gate",
    fake_precommit_gate,
  )

  files = [
    {
      "path": "src/App.jsx",
      "content": (
        'import { AiChat } from "./pages/AiChat";\n'
        'import { Layout } from "./components/Layout";\n'
        "export default function App(){ return <Layout><AiChat /></Layout>; }\n"
      ),
    },
    {"path": "src/pages/AiChat.jsx", "content": "export default function AiChat(){ return null; }\n"},
    {"path": "src/components/Layout.jsx", "content": "export default function Layout({children}){ return children; }\n"},
  ]
  tool_context = SimpleNamespace(store=VersionedFileStoreStub(files), settings=SimpleNamespace())
  events: list[dict] = []

  result = try_deterministic_module_contract_fix_streaming(
    prompt="fix import error",
    tool_context=tool_context,
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
  )

  assert result is not None
  assert upsert_calls
  assert result["runtime"]["changed_paths"] == ["src/App.jsx"]
  assert result["runtime"]["build_gate"]["status"] == "ready"
  assert result["runtime"]["visual_qa"]["status"] == "failed"
  assert any(event["step"] == "automation.precommit.visual_advisory" for event in events)


def test_deterministic_undefined_reference_fix_persists_when_visual_qa_fails(monkeypatch):
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  upsert_calls: list[dict] = []

  def fake_upsert(_tool_context, _user, payload):
    upsert_calls.append(payload)
    return {"project_id": payload["project_id"], "file_count": len(payload["files"])}

  def fake_precommit_gate(**kwargs):
    candidate_files = kwargs["candidate_files"]
    return (
      {"status": "ready", "candidate_files": candidate_files, "preview_url": "http://preview.local"},
      {"status": "failed", "issues": [{"severity": "low", "message": "Visual drift"}]},
    )

  monkeypatch.setattr(
    "backend.agentic.tools.handlers.upsert_project_files_tool",
    fake_upsert,
  )
  monkeypatch.setattr(
    "backend.agents.streaming.streaming_visual_qa.run_precommit_automation_gate",
    fake_precommit_gate,
  )

  dashboard = (
    "import React from 'react';\n"
    "export default function Dashboard() {\n"
    "  return (\n"
    "    <main>\n"
    "      {showOnboarding && (\n"
    "        <section>Tour overlay</section>\n"
    "      )}\n"
    "      <h1>Dashboard</h1>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )
  tool_context = SimpleNamespace(
    store=VersionedFileStoreStub([{"path": "src/pages/Dashboard.jsx", "content": dashboard}]),
    settings=SimpleNamespace(),
  )
  events: list[dict] = []

  result = try_deterministic_undefined_reference_fix_streaming(
    prompt="fix showOnboarding is not defined in src/pages/Dashboard.jsx",
    tool_context=tool_context,
    user=SimpleNamespace(id="user-1"),
    project_id="project-1",
    intent="simple_code",
    artifact_provider=SimpleNamespace(),
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
    update_analysis={
      "update_mode": "bug_fix",
      "summary": "Fix showOnboarding is not defined runtime crash.",
      "candidate_files": ["src/pages/Dashboard.jsx"],
    },
  )

  assert result is not None
  assert upsert_calls
  assert result["runtime"]["changed_paths"] == ["src/pages/Dashboard.jsx"]
  assert "showOnboarding" not in upsert_calls[0]["files"][0]["content"]
  assert any(event["step"] == "automation.precommit.visual_advisory" for event in events)
