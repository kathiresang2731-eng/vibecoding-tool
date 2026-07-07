from __future__ import annotations

from types import SimpleNamespace

from backend.agentic.tools.definitions import ToolRuntimeContext
from backend.agents.streaming.file_agent import _streaming_run_state, run_streaming_file_agent
from backend.agents.update_engine.contracts import UpdateScope
from backend.storage import UserContext


class _Store:
  def __init__(self) -> None:
    self.files = [
      {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
      {"path": "src/pages/Auth.jsx", "content": "export default function Auth() { return null; }"},
      {
        "path": "src/pages/Onboarding.jsx",
        "content": "export default function Onboarding() { return null; }",
      },
      {
        "path": "src/pages/Dashboard.jsx",
        "content": "export default function Dashboard() { return null; }",
      },
    ]
    self.events: list[dict] = []

  def list_files(self, project_id, user):
    _ = project_id, user
    return list(self.files)

  def get_project(self, project_id, user):
    _ = user
    return {"id": project_id, "name": "Demo", "local_path": None}

  def upsert_project_files(self, project_id, user, files, event_type=None, event_payload=None):
    _ = project_id, user, event_type, event_payload
    by_path = {item["path"]: item["content"] for item in self.files}
    for file_item in files:
      by_path[file_item["path"]] = file_item["content"]
    self.files = [{"path": path, "content": content} for path, content in sorted(by_path.items())]
    return len(files)

  def add_event(self, project_id, user_id, event_type, payload):
    self.events.append({"project_id": project_id, "user_id": user_id, "event_type": event_type, "payload": payload})


class _NoPatchProvider:
  name = "no-patch"

  def __init__(self) -> None:
    self.messages: list[list[dict]] = []

  def run_tool_loop(self, *, messages, **kwargs):
    _ = kwargs
    self.messages.append(messages)
    return {"status": "completed", "output_text": "Reviewed the flow.", "tool_calls": []}


class _VersionedStore(_Store):
  def create_version(self, *args, **kwargs):
    _ = args, kwargs
    return {"id": "version-1"}


class _DealsActionPlanProvider:
  name = "deals-action-plan"

  def __init__(self) -> None:
    self.messages: list[list[dict]] = []

  def run_tool_loop(self, *, messages, execute_tool, **kwargs):
    _ = kwargs
    self.messages.append(messages)
    result = execute_tool(
      "str_replace",
      {
        "path": "src/pages/Deals.jsx",
        "old_string": "window.alert('Action Plan created & synced for Acme Corp!');",
        "new_string": "setShowPlanModal(true);",
      },
    )
    assert result.get("status") == "staged"
    return {
      "status": "completed",
      "output_text": "Changed the create action plan interaction to open the modal.",
      "tool_calls": [{"tool": "str_replace", "path": "src/pages/Deals.jsx"}],
    }


def test_streaming_run_state_contract_for_saved_update_qa_outcomes() -> None:
  saved = [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]

  assert _streaming_run_state(
    intent="website_update",
    persisted_files=saved,
    empty_update=False,
    requirement_failed=False,
    build_gate_result={"status": "ready"},
    visual_qa_result={"status": "passed"},
    loop_status="completed",
  ) == "update_saved_preview_ready"

  assert _streaming_run_state(
    intent="website_update",
    persisted_files=saved,
    empty_update=False,
    requirement_failed=False,
    build_gate_result={"status": "ready"},
    visual_qa_result={"status": "failed", "code": "visual_qa_timeout", "advisory": True},
    loop_status="completed",
  ) == "update_saved_qa_inconclusive"

  assert _streaming_run_state(
    intent="website_update",
    persisted_files=[],
    empty_update=True,
    requirement_failed=False,
    build_gate_result=None,
    visual_qa_result=None,
    loop_status="completed",
  ) == "update_failed_no_changes"


class _ThemeToolLoopProvider:
  name = "theme-tool-loop"

  def __init__(self) -> None:
    self.messages: list[list[dict]] = []

  def run_tool_loop(self, *, messages, execute_tool, **kwargs):
    _ = kwargs
    self.messages.append(messages)
    css_result = execute_tool(
      "str_replace",
      {
        "path": "src/index.css",
        "old_string": "body { background: #ffffff; color: #111827; }\n",
        "new_string": "body { background: #000000; color: #ffffff; }\n",
      },
    )
    app_result = execute_tool(
      "str_replace",
      {
        "path": "src/App.jsx",
        "old_string": "bg-slate-50 text-indigo-700",
        "new_string": "bg-black text-red-500",
      },
    )
    dashboard_result = execute_tool(
      "str_replace",
      {
        "path": "src/pages/Dashboard.jsx",
        "old_string": "from-indigo-950 via-purple-900 to-slate-950 border-purple-500/40 text-slate-100",
        "new_string": "from-red-950 via-black to-black border-red-500/40 text-white",
      },
    )
    assert css_result.get("status") == "staged"
    assert app_result.get("status") == "staged"
    assert dashboard_result.get("status") == "staged"
    return {
      "status": "completed",
      "output_text": "Updated the visual theme using scoped project files.",
      "tool_calls": [
        {"tool": "str_replace", "path": "src/index.css"},
        {"tool": "str_replace", "path": "src/App.jsx"},
        {"tool": "str_replace", "path": "src/pages/Dashboard.jsx"},
      ],
    }


class _SyntaxThenValidProvider:
  name = "syntax-then-valid"

  def __init__(self) -> None:
    self.messages: list[list[dict]] = []

  def run_tool_loop(self, *, messages, execute_tool, **kwargs):
    _ = kwargs
    self.messages.append(messages)
    if len(self.messages) == 1:
      result = execute_tool(
        "str_replace",
        {
          "path": "src/App.jsx",
          "old_string": "export default function App() { return null; }",
          "new_string": "export default function App() { return <main>Auth</main>;\n",
        },
      )
      assert result.get("syntax_blocked") is True
      return {"status": "completed", "output_text": "Tried to add auth gate.", "tool_calls": []}
    result = execute_tool(
      "str_replace",
      {
        "path": "src/App.jsx",
        "old_string": "return null;",
        "new_string": "return <main>Auth</main>;",
      },
    )
    assert result.get("status") == "staged"
    return {"status": "completed", "output_text": "Added auth gate safely.", "tool_calls": []}


class _MaxStepThenPatchProvider:
  name = "max-step-then-patch"

  def __init__(self) -> None:
    self.messages: list[list[dict]] = []
    self.max_steps: list[int] = []

  def run_tool_loop(self, *, messages, execute_tool, max_steps, **kwargs):
    _ = kwargs
    self.messages.append(messages)
    self.max_steps.append(max_steps)
    if len(self.messages) == 1:
      raise RuntimeError("Gemini tool-calling loop exceeded 2 steps.")
    result = execute_tool(
      "str_replace",
      {
        "path": "src/index.css",
        "old_string": "body { background: #ffffff; color: #111827; }\n",
        "new_string": "body { background: #000000; color: #ffffff; }\n",
      },
    )
    assert result.get("status") == "staged"
    return {"status": "completed", "output_text": "Updated theme colors.", "tool_calls": []}


def test_auth_flow_zero_patch_is_failed_not_completed(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="feature_patch",
    candidate_files=[
      "src/App.jsx",
      "src/pages/Auth.jsx",
      "src/pages/Onboarding.jsx",
      "src/pages/Dashboard.jsx",
    ],
    candidate_new_files=[],
    summary="Implement sign-in then onboarding then dashboard.",
    scope_rationale="Auth flow files.",
    scoped_update_tasks=[],
    preflight_source="test",
    llm_analysis_used=False,
    request_kind="flow_patch",
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  provider = _NoPatchProvider()
  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=_Store(), settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt="first user must sign in then onboarding then dashboard",
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda *_args, **_kwargs: None,
    skip_workspace_pull=True,
    skip_build_gate=True,
    target_resolution={
      "resolved_page": "Auth",
      "resolved_route": "/auth",
      "resolved_files": ["src/pages/Auth.jsx"],
      "confidence": 0.88,
      "source": "current_prompt_page",
    },
  )

  assert len(provider.messages) == 2
  assert "AUTH / ONBOARDING FLOW PATCH REQUIRED" in provider.messages[0][1]["content"]
  assert "Previous attempt produced ZERO file edits" in provider.messages[1][1]["content"]
  assert result["runtime"]["status"] == "failed"
  assert result["runtime"]["no_code_changes"] is True
  assert "no effective file changes" in result["runtime"]["output_text"]
  assert "request_kind=flow_patch" in result["runtime"]["output_text"]
  assert "src/App.jsx" in result["runtime"]["output_text"]
  assert result["runtime"]["commit_result"]["persisted"] is False
  assert result["runtime"]["diagnostic_report"]["target_resolution"]["resolved_files"] == ["src/pages/Auth.jsx"]
  assert result["generated_website"]["files"] == []


def test_website_update_saves_staged_edit_before_qa_when_store_supports_versions(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="bug_fix",
    candidate_files=["src/pages/Deals.jsx"],
    candidate_new_files=[],
    summary="Open the action plan as a modal instead of an alert.",
    scope_rationale="The create action plan button lives in Deals.jsx.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="interaction_wiring_update",
    target_files=["src/pages/Deals.jsx"],
    raw_analysis={"execution_strategy": "scoped_model_patch"},
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setattr(
    "backend.agents.streaming.build_gate.post_update_build_gate_enabled",
    lambda: False,
  )

  def fail_precommit(**kwargs):
    _ = kwargs
    raise AssertionError("website updates must save before QA instead of running precommit")

  monkeypatch.setattr(
    "backend.agents.streaming.streaming_visual_qa.run_precommit_automation_gate",
    fail_precommit,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")

  store = _VersionedStore()
  store.files = [
    {
      "path": "src/pages/Deals.jsx",
      "content": (
        "import { useState } from 'react';\n"
        "export default function Deals() {\n"
        "  const [showPlanModal, setShowPlanModal] = useState(false);\n"
        "  const createActionPlan = () => {\n"
        "    window.alert('Action Plan created & synced for Acme Corp!');\n"
        "  };\n"
        "  return <main><button onClick={createActionPlan}>Create Action Plan</button>"
        "{showPlanModal && <section role=\"dialog\">Action Plan</section>}</main>;\n"
        "}\n"
      ),
    },
  ]
  provider = _DealsActionPlanProvider()

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt=(
      "in Manage Your Deals & Opportunities page while clicking the create action plan "
      "button provide a modal not a popup message"
    ),
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda *_args, **_kwargs: None,
    skip_workspace_pull=True,
    skip_build_gate=False,
  )

  assert result["runtime"]["status"] == "completed"
  assert result["runtime"]["commit_result"]["persisted"] is True
  assert result["runtime"]["commit_result"]["saved_paths"] == ["src/pages/Deals.jsx"]
  assert provider.messages == []
  assert result["generated_website"]["files"]
  deals = next(item["content"] for item in store.files if item["path"] == "src/pages/Deals.jsx")
  assert "setShowCreateActionPlanModal(true)" in deals
  assert "window.alert" not in deals


def test_interaction_no_patch_recovers_from_exact_button_and_route_anchors(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="bug_fix",
    candidate_files=[
      "src/pages/Analytics.jsx",
      "src/App.jsx",
      "src/pages/Onboarding.jsx",
    ],
    candidate_new_files=[],
    summary="Wire the analytics walkthrough button to the onboarding route.",
    scope_rationale="UI knowledge located the exact button owner and existing destination route.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="interaction_wiring_update",
    target_files=["src/pages/Analytics.jsx"],
    reference_files=["src/App.jsx", "src/pages/Onboarding.jsx"],
    enrichment_profile="interaction_wiring",
    interaction_summary="Start Onboarding Walkthrough button should navigate to onboarding.",
    interaction={
      "component": "Start Onboarding Walkthrough button",
      "trigger": "click",
      "expected": "redirect to onboarding page",
      "source_page": "Advanced Analytics Portal",
      "target_page_or_route": "Onboarding",
      "confidence": 0.96,
    },
    raw_analysis={"execution_strategy": "scoped_model_patch"},
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")

  store = _Store()
  store.files = [
    {
      "path": "src/App.jsx",
      "content": (
        "import { HashRouter, Routes, Route } from './worktual-router-shim.jsx';\n"
        "import Analytics from './pages/Analytics.jsx';\n"
        "import Onboarding from './pages/Onboarding.jsx';\n"
        "export default function App() { return <HashRouter><Routes>"
        "<Route path=\"/analytics\" element={<Analytics />} />"
        "<Route path=\"/onboarding\" element={<Onboarding />} />"
        "</Routes></HashRouter>; }\n"
      ),
    },
    {
      "path": "src/worktual-router-shim.jsx",
      "content": "export { HashRouter, Routes, Route, useNavigate } from 'react-router-dom';\n",
    },
    {
      "path": "src/pages/Analytics.jsx",
      "content": (
        "export default function Analytics() {\n"
        "  return <main><h1>Advanced Analytics Portal</h1>"
        "<button type=\"button\">Start Onboarding Walkthrough</button></main>;\n"
        "}\n"
      ),
    },
    {
      "path": "src/pages/Onboarding.jsx",
      "content": "export default function Onboarding() { return <main>Onboarding</main>; }\n",
    },
  ]
  provider = _NoPatchProvider()
  events: list[dict] = []

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt=(
      "in Advanced Analytics Portal page Start Onboarding Walkthrough button "
      "not working to redirect to the onboarding page"
    ),
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda step, message, **kwargs: events.append(
      {"step": step, "message": message, **kwargs}
    ),
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert provider.messages == []
  assert any(event["step"] == "update.deterministic_patch.applied" for event in events)
  assert any(event["step"] == "agent.runtime.loop.skipped" for event in events)
  assert result["runtime"]["status"] == "completed"
  assert result["runtime"]["commit_result"]["saved_paths"] == ["src/pages/Analytics.jsx"]
  analytics = next(item["content"] for item in store.files if item["path"] == "src/pages/Analytics.jsx")
  assert "useNavigate" in analytics
  assert "navigate('/onboarding')" in analytics


def test_interaction_no_patch_recovers_create_action_plan_modal(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="bug_fix",
    candidate_files=["src/pages/Deals.jsx"],
    candidate_new_files=[],
    summary="Open Create Action Plan as a modal.",
    scope_rationale="The Create Action Plan button lives in Deals.jsx.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="interaction_wiring_update",
    target_files=["src/pages/Deals.jsx"],
    enrichment_profile="interaction_wiring",
    interaction_summary="Create Action Plan button should open a modal instead of doing nothing.",
    interaction={
      "component": "Create Action Plan button",
      "trigger": "click",
      "expected": "open modal",
      "source_page": "Manage Your Deals & Opportunities",
      "confidence": 0.94,
    },
    raw_analysis={"execution_strategy": "scoped_model_patch"},
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")

  store = _Store()
  store.files = [
    {
      "path": "src/pages/Deals.jsx",
      "content": (
        "import React from 'react';\n"
        "export default function Deals() {\n"
        "  return <main><h1>Manage Your Deals & Opportunities</h1>"
        "<button type=\"button\" onClick={() => window.alert('Action Plan created & synced for Acme Corp!')}>"
        "Create Action Plan</button></main>;\n"
        "}\n"
      ),
    },
  ]
  provider = _NoPatchProvider()
  events: list[dict] = []

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt=(
      "in Manage Your Deals & Opportunities page we have create action plan right? "
      "while click that button no action is happened but want to add as modal"
    ),
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda step, message, **kwargs: events.append(
      {"step": step, "message": message, **kwargs}
    ),
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert provider.messages == []
  assert any(event["step"] == "update.deterministic_patch.applied" for event in events)
  assert any(event["step"] == "agent.runtime.loop.skipped" for event in events)
  assert result["runtime"]["status"] == "completed"
  assert result["runtime"]["commit_result"]["saved_paths"] == ["src/pages/Deals.jsx"]
  deals = next(item["content"] for item in store.files if item["path"] == "src/pages/Deals.jsx")
  assert "useState" in deals
  assert "showCreateActionPlanModal" in deals
  assert "setShowCreateActionPlanModal(true)" in deals
  assert "setShowCreateActionPlanModal(false)" in deals
  assert "window.alert" not in deals
  assert "The requested action is ready to continue from this modal" in deals


def test_local_first_interaction_update_can_be_disabled(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="bug_fix",
    candidate_files=["src/pages/Deals.jsx"],
    candidate_new_files=[],
    summary="Open Create Action Plan as a modal.",
    scope_rationale="The Create Action Plan button lives in Deals.jsx.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="interaction_wiring_update",
    target_files=["src/pages/Deals.jsx"],
    enrichment_profile="interaction_wiring",
    interaction={
      "component": "Create Action Plan button",
      "trigger": "click",
      "expected": "open modal",
      "source_page": "Manage Your Deals & Opportunities",
      "confidence": 0.94,
    },
    raw_analysis={"execution_strategy": "scoped_model_patch"},
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
  monkeypatch.setenv("ENABLE_LOCAL_FIRST_INTERACTION_UPDATES", "false")

  store = _Store()
  store.files = [
    {
      "path": "src/pages/Deals.jsx",
      "content": (
        "import React from 'react';\n"
        "export default function Deals() {\n"
        "  return <main><h1>Manage Your Deals & Opportunities</h1>"
        "<button type=\"button\">Create Action Plan</button></main>;\n"
        "}\n"
      ),
    },
  ]
  provider = _NoPatchProvider()
  events: list[dict] = []

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt="Create Action Plan button should open as modal not popup",
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert len(provider.messages) == 2
  assert any(event["step"] == "update.deterministic_patch.disabled" for event in events)
  assert any(event["step"] == "update.empty_patch.recovered" for event in events)
  assert result["runtime"]["status"] == "completed"
  deals = next(item["content"] for item in store.files if item["path"] == "src/pages/Deals.jsx")
  assert "setShowCreateActionPlanModal(true)" in deals


def test_unified_scope_theme_update_uses_agentic_tool_loop(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="targeted_patch",
    candidate_files=["src/index.css", "src/App.jsx", "src/pages/Dashboard.jsx"],
    candidate_new_files=[],
    summary="Apply the requested red and black theme.",
    scope_rationale="Theme updates should touch shared CSS and visible page files.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="theme_color_update",
    target_files=["src/index.css", "src/App.jsx", "src/pages/Dashboard.jsx"],
    raw_analysis={
      "execution_strategy": "scoped_model_patch",
      "targeted_patch": {
        "kind": "theme_color_update",
        "primary_hex": "#dc2626",
        "secondary_hex": "#000000",
        "background_hex": "#000000",
        "text_hex": "#ffffff",
      },
    },
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_STREAMING_PATH_PARITY", "true")
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  store = _Store()
  store.files = [
    {"path": "index.html", "content": "<title>Demo</title>"},
    {
      "path": "src/index.css",
      "content": "body { background: #ffffff; color: #111827; }\n",
    },
    {
      "path": "src/App.jsx",
      "content": "export default function App() { return <main className=\"bg-slate-50 text-indigo-700\">CRM</main>; }",
    },
    {
      "path": "src/pages/Dashboard.jsx",
      "content": "export default function Dashboard() { return <section className=\"from-indigo-950 via-purple-900 to-slate-950 border-purple-500/40 text-slate-100\">Dashboard</section>; }",
    },
  ]
  provider = _ThemeToolLoopProvider()
  events: list[dict] = []

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt="change the website theme to red & black",
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert provider.messages
  assert "Priority visual/theme files from project memory/search" in provider.messages[0][1]["content"]
  assert "edit the relevant workspace file directly" in provider.messages[0][1]["content"]
  assert result["runtime"]["status"] == "completed"
  assert result["generated_website"]["files"]
  updated_css = next(item for item in store.files if item["path"] == "src/index.css")["content"]
  updated_app = next(item for item in store.files if item["path"] == "src/App.jsx")["content"]
  updated_dashboard = next(item for item in store.files if item["path"] == "src/pages/Dashboard.jsx")["content"]
  assert "background: #000000" in updated_css
  assert "bg-black" in updated_app
  assert "text-red-500" in updated_app
  assert "from-red-950" in updated_dashboard
  assert "via-black" in updated_dashboard
  assert "to-black" in updated_dashboard
  assert "border-red-500/40" in updated_dashboard
  assert result["runtime"]["update_scope"]["request_kind"] == "theme_color_update"
  assert result["runtime"]["commit_result"]["saved_paths"] == [
    "src/App.jsx",
    "src/index.css",
    "src/pages/Dashboard.jsx",
  ]


def test_syntax_blocked_update_retries_once_with_exact_failure_context(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="feature_patch",
    candidate_files=["src/App.jsx"],
    candidate_new_files=[],
    summary="Add auth before dashboard.",
    scope_rationale="Auth flow starts in App.",
    scoped_update_tasks=[],
    preflight_source="test",
    llm_analysis_used=False,
    request_kind="flow_patch",
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")

  store = _Store()
  provider = _SyntaxThenValidProvider()
  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt="Before reaching the dashboard user must sign in and login",
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda *_args, **_kwargs: None,
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert len(provider.messages) == 2
  assert "Syntax/tool failure context from the previous attempt" in provider.messages[1][1]["content"]
  assert "unbalanced" in provider.messages[1][1]["content"]
  assert result["runtime"]["commit_result"]["persisted"] is True
  assert result["runtime"]["commit_result"]["saved_paths"] == ["src/App.jsx"]
  assert next(item for item in store.files if item["path"] == "src/App.jsx")["content"] == (
    "export default function App() { return <main>Auth</main>; }"
  )


def test_step_exhausted_zero_patch_retries_and_saves_edit(monkeypatch) -> None:
  scope = UpdateScope(
    update_mode="targeted_patch",
    candidate_files=["src/index.css"],
    candidate_new_files=[],
    summary="Apply requested red and black theme.",
    scope_rationale="Shared stylesheet owns base theme colors.",
    scoped_update_tasks=[],
    preflight_source="scope_engine_llm",
    llm_analysis_used=True,
    request_kind="theme_color_update",
    target_files=["src/index.css"],
    raw_analysis={
      "execution_strategy": "scoped_model_patch",
      "targeted_patch": {
        "kind": "theme_color_update",
        "primary_hex": "#dc2626",
        "secondary_hex": "#000000",
        "background_hex": "#000000",
        "text_hex": "#ffffff",
      },
    },
  )
  monkeypatch.setattr(
    "backend.agents.update_engine.scope_engine.resolve_update_scope",
    lambda **kwargs: scope,
  )
  monkeypatch.setenv("ENABLE_PATCH_APPROVAL", "false")
  monkeypatch.setenv("ENABLE_UNIFIED_UPDATE_ENGINE", "true")
  monkeypatch.setenv("ENABLE_LEGACY_PARALLEL_UPDATES", "false")
  monkeypatch.setenv("STREAMING_FILE_AGENT_UPDATE_MAX_STEPS", "2")

  store = _Store()
  store.files.append({"path": "src/index.css", "content": "body { background: #ffffff; color: #111827; }\n"})
  provider = _MaxStepThenPatchProvider()
  events: list[dict] = []

  result = run_streaming_file_agent(
    project_id="project-1",
    user=UserContext(id="user-1", email="user@example.com", role="user"),
    tool_context=ToolRuntimeContext(store=store, settings=SimpleNamespace()),  # type: ignore[arg-type]
    prompt="then change this page theme and color to red & black - Advanced Analytics Portal",
    intent="website_update",
    artifact_provider=provider,
    emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
    skip_workspace_pull=True,
    skip_build_gate=True,
  )

  assert len(provider.messages) == 2
  assert provider.max_steps[0] >= 8
  assert provider.max_steps[1] >= 8
  assert "Previous tool loop stopped because the step budget was exhausted" in provider.messages[1][1]["content"]
  assert any(event["step"] == "update.empty_patch.retry" for event in events)
  assert result["runtime"]["status"] == "completed"
  assert result["runtime"]["commit_result"]["saved_paths"] == ["src/index.css"]
  updated_css = next(item for item in store.files if item["path"] == "src/index.css")["content"]
  assert "background: #000000" in updated_css
  assert "color: #ffffff" in updated_css
