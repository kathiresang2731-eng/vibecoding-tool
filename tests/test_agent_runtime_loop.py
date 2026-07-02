import json
import time

import pytest

from backend.audit_logging import RunTelemetryContext, current_telemetry_context, telemetry_scope
from backend.agent_tools import ToolRuntimeContext
from backend.llm.agent_runtime_loop import (
  AgentRuntimeLoopError,
  ScopedUpdateGuardError,
  artifact_call_soft_timeout_seconds,
  artifact_model_soft_timeout_seconds,
  build_project_state_memory,
  build_update_code_search_matches,
  enforce_loop_budget,
  ensure_tailwind_runtime_files,
  ensure_vite_scaffold_files,
  emit_candidate_code_diff_progress,
  execute_real_agent_runtime_loop,
  is_artifact_json_invalid_error,
  repair_model_soft_timeout_seconds,
  scoped_update_sequence_timeout_seconds,
  scoped_update_model_soft_timeout_seconds,
  run_scoped_update_agent,
  run_planner_agent,
  run_prompt_analyst_agent,
  run_code_agent,
  run_artifact_provider_with_soft_timeout,
  runtime_timeout_seconds,
  should_use_deterministic_artifact_fallback,
  normalize_update_analysis,
  validate_scoped_update_changes,
)
from backend.llm.agent_runtime.actions.project_io import is_unresolved_preview_runtime_import_reason, small_scoped_update_static_qa_reason
from backend.llm.agent_runtime.actions.analysis import update_request_summary_message, update_request_summary_progress_detail
from backend.llm.agent_runtime.constants import (
  SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS,
  SCOPED_UPDATE_MAX_OUTPUT_TOKENS,
)
from backend.llm.agent_runtime.error_handling import analyze_error_context
from backend.llm.agent_runtime.fallbacks import is_model_connection_error
from backend.llm.agent_runtime.scaffolding import normalize_frontend_runtime_imports, router_shim_code
from backend.llm.agent_runtime.supervision import available_runtime_actions
from backend.llm.agent_runtime.targeted_updates import apply_targeted_file_update
from backend.llm.agent_runtime.update_analysis import targeted_update_request_from_analysis
from backend.llm.dynamic_agents import reset_global_agent_registry
from backend.llm.gemini_client import parse_json_text
from backend.llm.mas import MASContractError, assert_mas_action_allowed
from backend.llm.prompts import build_website_prompt
from backend.llm.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE
from tests.runtime_test_helpers import (
  BOOTSTRAP_ACTION,
  BOOTSTRAP_TOOLS,
  assert_bootstrap_tool_calls,
  bootstrap_mas_action,
  assert_bootstrap_mas_step,
  generation_action_history,
  scoped_update_action_history,
  scoped_update_action_prefix,
)


RAW_APP_CODE = "export default function App() { return <main>ok</main>; }"
NORMALIZED_APP_CODE = f'import React from "react";\n{RAW_APP_CODE}'

pytestmark = pytest.mark.usefixtures("use_direct_generation_workflow_in_tests")


def assert_incremental_write_before_preview_calls(calls):
  write_indexes = [index for index, name in enumerate(calls) if name == "WRITE_PROJECT_FILES"]
  if write_indexes and "VALIDATE_PROJECT_ARTIFACT" in calls:
    assert min(write_indexes) < calls.index("VALIDATE_PROJECT_ARTIFACT")
  if write_indexes and "RUN_PREVIEW_VISUAL_QA" in calls:
    assert max(write_indexes) < calls.index("RUN_PREVIEW_VISUAL_QA")
  if "PERSIST_PROJECT_MEMORY" in calls:
    assert calls[-1] == "PERSIST_PROJECT_MEMORY"
  assert_bootstrap_tool_calls(calls)


def assert_written_files_match_preview(written_files, preview_files):
  written_by_path = {file_item["path"]: file_item["content"] for file_item in written_files[-1]}
  preview_by_path = {file_item["path"]: file_item["content"] for file_item in preview_files[0]}
  assert written_by_path == preview_by_path


def test_candidate_code_diff_progress_emits_added_files_for_empty_project():
  state = {
    "read_result": {"files": []},
    "candidate_files": [{"path": "src/App.jsx", "content": "export default function App() { return <main />; }\n"}],
  }
  events = []

  def progress(step, message, **kwargs):
    events.append({"step": step, "message": message, **kwargs})

  diff = emit_candidate_code_diff_progress(
    state,
    progress,
    stage="code_candidate_prepared",
    message_prefix="Prepared generated code changes",
  )

  assert diff["file_count"] == 1
  assert diff["added"] == 1
  assert diff["removed"] == 0
  assert state["code_diff_summary"]["file_count"] == 1
  assert "diff" not in state["code_diff_summary"]["files"][0]
  steps = [event["step"] for event in events]
  assert "patch.proposed" in steps
  assert "file.diff.ready" in steps
  diff_event = next(event for event in events if event["step"] == "file.diff.ready")
  assert diff_event["detail"]["stage"] == "code_candidate_prepared"
  assert diff_event["audit_detail"]["stage"] == "code_candidate_prepared"
  assert "Prepared generated code changes: 1 files, +1 / -0" in diff_event["message"]


def test_small_scoped_bug_update_uses_static_fast_qa_reason():
  state = {
    "prompt": "still while click the New Project button no modal is came",
    "update_analysis": {"scope": "small", "update_mode": "bug_fix"},
    "changed_file_paths": ["src/App.jsx"],
  }

  reason = small_scoped_update_static_qa_reason(state)

  assert "browser visual QA skipped for speed" in reason


def test_visual_small_update_still_requires_browser_qa():
  state = {
    "prompt": "fix the mobile layout overlap in the header",
    "update_analysis": {"scope": "small", "update_mode": "bug_fix"},
    "changed_file_paths": ["src/App.jsx"],
  }

  assert small_scoped_update_static_qa_reason(state) == ""


def test_background_color_update_uses_model_selected_targeted_patch():
  analysis = normalize_update_analysis(
    {
      "update_mode": "targeted_patch",
      "request_kind": "theme_color_update",
      "execution_strategy": "deterministic_patch",
      "scope": "small",
      "summary": "Change the main background color.",
      "candidate_files": ["style.css"],
      "targeted_patch": {"kind": "theme_color_update", "colors": ["green"]},
      "allow_full_regeneration": False,
    },
    existing_paths=["style.css", "src/App.jsx"],
    code_search_matches=[],
    user_prompt="change background color",
  )

  assert analysis["update_mode"] == "targeted_patch"
  assert analysis["execution_strategy"] == "deterministic_patch"
  assert analysis["request_kind"] == "theme_color_update"
  assert analysis["targeted_patch"]["colors"] == ["green"]

  request = targeted_update_request_from_analysis(analysis)
  changed = apply_targeted_file_update(
    [{"path": "style.css", "content": "body { background: #ffffff; color: #111827; }\n"}],
    request,
  )

  assert changed[0]["path"] == "style.css"
  assert "--vibe-theme-background: #dcfce7;" in changed[0]["content"]
  assert "background: var(--vibe-theme-background);" in changed[0]["content"]


def test_error_handling_agent_detects_js_api_and_data_shape_errors():
  prompt = """
  :8787/api/contacts Failed to load resource: the server responded with a status of 404 (Not Found)
  :8787/api/deals Failed to load resource: the server responded with a status of 404 (Not Found)
  Uncaught TypeError: v.map is not a function
  """
  existing_files = [
    {"path": "src/App.jsx", "content": "fetch('/api/contacts')"},
    {"path": "src/pages/Projects.jsx", "content": "projects.map((item) => item.name)"},
    {"path": "backend/routes.py", "content": "from fastapi import APIRouter"},
  ]

  diagnosis = analyze_error_context(prompt, existing_files=existing_files)

  assert "javascript" in diagnosis["languages"]
  assert "missing_api_route" in diagnosis["categories"]
  assert "data_shape_mismatch" in diagnosis["categories"]
  assert "/api/contacts" in diagnosis["api_routes"]
  assert diagnosis["candidate_files"][:2] == ["backend/routes.py", "src/App.jsx"]
  assert diagnosis["strategy"] == "single_orchestrating_agent_with_language_specific_diagnostics"


def test_error_handling_agent_detects_undefined_name_runtime_error():
  prompt = "Uncaught TypeError: Cannot read properties of undefined (reading 'name') at Dashboard.jsx"
  existing_files = [
    {"path": "src/App.jsx", "content": "return <Dashboard config={config} />"},
    {"path": "src/components/Dashboard.jsx", "content": "export default function Dashboard({ config }) { return <h1>{config.name}</h1>; }"},
  ]

  diagnosis = analyze_error_context(prompt, existing_files=existing_files)

  assert "javascript" in diagnosis["languages"]
  assert "runtime_exception" in diagnosis["categories"]
  assert "data_shape_mismatch" in diagnosis["categories"]
  assert diagnosis["candidate_files"][:2] == ["src/App.jsx", "src/components/Dashboard.jsx"]
  assert any(".name" in hint for hint in diagnosis["root_cause_hints"])


def test_supervisor_exposes_error_handling_without_prompt_regex_routing():
  state = {
    "operation": "update",
    "prompt": "Uncaught TypeError: v.map is not a function at Projects.jsx",
    "read_result": {"files": [{"path": "src/pages/Projects.jsx", "content": "const v = {}; v.map(Boolean);"}]},
    "memory_result": {"memories": []},
    "generated_website": None,
    "update_analysis": None,
    "error_diagnosis": None,
  }

  actions = available_runtime_actions(state, max_repair_attempts=1)

  assert [action["name"] for action in actions] == ["RUN_UPDATE_ANALYST", "RUN_ERROR_HANDLING_AGENT"]


def test_normalize_update_analysis_uses_error_diagnosis_candidate_files():
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Fix project module crash",
      "candidate_files": ["src/App.jsx"],
      "candidate_new_files": [],
      "feature_plan": {"name": "ProjectModuleFix", "type": "helper", "items": [], "interaction": "Click project module"},
      "targeted_patch": {"kind": "other"},
      "allow_full_regeneration": False,
    },
    existing_paths=["src/App.jsx", "src/pages/Projects.jsx", "src/components/Header.jsx"],
    code_search_matches=[],
    user_prompt="Uncaught TypeError: v.map is not a function",
    error_diagnosis={
      "categories": ["runtime_exception", "data_shape_mismatch"],
      "candidate_files": ["src/pages/Projects.jsx", "src/components/Header.jsx", "src/App.jsx"],
    },
  )

  assert result["update_mode"] == "bug_fix"
  assert result["request_kind"] == "bug_fix"
  assert result["candidate_files"][0] == "src/pages/Projects.jsx"
  assert len(result["candidate_files"]) == 2
  assert result["error_diagnosis"]["categories"] == ["runtime_exception", "data_shape_mismatch"]


def test_candidate_code_diff_progress_deduplicates_identical_candidate_files():
  state = {
    "read_result": {"files": [{"path": "src/App.jsx", "content": "old\n"}]},
    "candidate_files": [{"path": "src/App.jsx", "content": "old\nnew\n"}],
  }
  events = []

  def progress(step, message, **kwargs):
    events.append({"step": step, "message": message, **kwargs})

  emit_candidate_code_diff_progress(state, progress, stage="scoped_update_prepared")
  emit_candidate_code_diff_progress(state, progress, stage="commit_ready")
  assert len(events) == 1

  state["candidate_files"] = [{"path": "src/App.jsx", "content": "old\nnew\nnext\n"}]
  emit_candidate_code_diff_progress(state, progress, stage="preview_candidate_prepared")

  assert len(events) == 2
  assert events[1]["detail"]["added"] == 2
  assert events[1]["detail"]["stage"] == "preview_candidate_prepared"


def test_project_state_memory_records_latest_update_without_code_bodies():
  state = {
    "operation": "website_update",
    "prompt": "Add a notification menu when the bell icon is clicked.",
    "generated_website": {"title": "Aura CRM"},
    "update_analysis": {
      "request_kind": "feature_patch",
      "update_mode": "feature_patch",
      "execution_strategy": "scoped_existing_project_update",
    },
    "scoped_update": {
      "status": "applied",
      "update_mode": "feature_patch",
      "changed_file_paths": ["src/components/Dashboard.jsx"],
    },
    "read_result": {
      "files": [{"path": "src/components/Dashboard.jsx", "content": "export default function Dashboard(){return null;}\n"}],
    },
    "candidate_files": [
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard(){return <button>Notifications</button>;}\n",
      }
    ],
    "preview": {"status": "built"},
    "preview_result": {"version": {"status": "ready", "preview_url": "/api/previews/p/v/"}},
    "visual_qa_result": {"status": "passed"},
    "committed": True,
  }

  memory = build_project_state_memory(state, project_id="project-1")
  serialized = json.dumps(memory)

  assert memory["operation"] == "website_update"
  assert memory["agent_path"] == "scoped_update"
  assert memory["changed_file_paths"] == ["src/components/Dashboard.jsx"]
  assert memory["preview"]["status"] == "built"
  assert memory["visual_qa_status"] == "passed"
  assert memory["diff"]["files"][0]["new_hash"]
  assert "return <button>Notifications</button>" not in serialized
  assert "export default function Dashboard" not in serialized


def valid_artifact(title="Agentic CRM"):
  return {
    "generated_website": {
      "title": title,
      "headline": "Pipeline clarity",
      "subheadline": "A real agent runtime test.",
      "primary_cta": "Start",
      "secondary_cta": "Preview",
      "preview_html": "",
      "theme": {
        "colors": {
          "primary": "#000000",
          "secondary": "#7c3aed",
          "accent": "#111827",
          "background": "#ffffff",
          "text": "#111827",
        },
      },
      "sections": [
        {
          "name": "Hero",
          "purpose": "Introduce the site.",
          "content": "Hero content.",
          "items": ["Headline", "CTA"],
        }
      ],
      "files": [
        {
          "path": "src/App.jsx",
          "purpose": "Generated app.",
          "code": RAW_APP_CODE,
        }
      ],
    },
    "implementation_notes": {
      "recommended_next_actions": ["Review preview"],
    },
  }


class FakeControlProvider:
  name = "fake-control"
  provider_role = CONTROL_PROVIDER_ROLE

  def generate_json(self, prompt, **kwargs):
    if kwargs.get("trace_label") == "prompt_analyst_agent":
      return {
        "business_type": "CRM",
        "audience": "Sales teams",
        "goal": "Generate a CRM website",
        "style": "Black and purple",
        "required_sections": ["Hero", "Features"],
        "missing_information": [],
      }
    if kwargs.get("trace_label") == "update_analysis_agent":
      user_request = prompt.split("Existing project file index:", 1)[0]
      lowered = user_request.lower()
      if "change the main files also not only index.html" in lowered:
        return {
          "update_mode": "needs_clarification",
          "request_kind": "other",
          "execution_strategy": "clarify",
          "scope": "small",
          "summary": "The requested source-file change is ambiguous.",
          "target_symbols": [],
          "candidate_files": [],
          "required_agents": [],
          "preserve_rules": ["Preserve every existing file."],
          "allow_full_regeneration": False,
          "clarification_question": "Should I update only the existing brand text across source files, or rebuild the website around a new topic?",
          "reason": "The user did not identify the value or feature to change.",
        }
      targeted_kind = None
      targeted_patch = {"kind": "other"}
      if "background color to red and yellow" in lowered:
        targeted_kind = "theme_color_update"
        targeted_patch = {
          "kind": targeted_kind,
          "colors": ["red", "yellow"],
          "target_description": "Apply the requested red/yellow theme to existing files.",
        }
      elif "website name to" in lowered or "rebrand from" in lowered:
        targeted_kind = "brand_name_update"
        if "yoga & choga" in lowered:
          new_value = "Yoga & Choga"
          old_value = ""
        elif "worktual" in lowered:
          new_value = "Worktual" if "rebrand from" in lowered else "worktual"
          old_value = "MeadowBrook Farms" if "rebrand from" in lowered else ""
        else:
          new_value = "Updated Brand"
          old_value = ""
        targeted_patch = {
          "kind": targeted_kind,
          "old_value": old_value,
          "new_value": new_value,
          "target_description": "Update high-confidence brand text and metadata.",
        }
      elif "page size to 25" in lowered:
        targeted_kind = "pagination_page_size_update"
        targeted_patch = {
          "kind": targeted_kind,
          "page_size": 25,
          "target_description": "Update the existing pagination page-size constant.",
        }
      if targeted_kind:
        return {
          "update_mode": "targeted_patch",
          "request_kind": targeted_kind,
          "execution_strategy": "deterministic_patch",
          "scope": "small",
          "summary": "Apply the requested deterministic existing-project update.",
          "target_symbols": [],
          "candidate_files": ["index.html", "src/App.jsx"],
          "required_agents": ["targeted_update_agent"],
          "preserve_rules": ["Preserve every unrelated existing project file."],
          "targeted_patch": targeted_patch,
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "The request is a supported model-selected targeted update.",
        }
      return {
        "update_mode": "feature_patch",
        "request_kind": "feature_patch",
        "execution_strategy": "scoped_model_patch",
        "scope": "small",
        "summary": "Update the requested existing-project feature.",
        "target_symbols": ["App"],
        "candidate_files": ["src/App.jsx"],
        "required_agents": ["feature_patch_agent"],
        "preserve_rules": ["Preserve every unrelated existing project file."],
        "allow_full_regeneration": False,
        "clarification_question": "",
        "reason": "The request is a bounded existing-project feature update.",
      }
    return {
      "sections": ["Hero", "Features"],
      "layout_strategy": "Responsive landing page",
      "interactions": ["CTA"],
      "quality_checks": ["Build passes"],
    }


class CapturingControlProvider(FakeControlProvider):
  def __init__(self):
    self.prompts_by_label = {}

  def generate_json(self, prompt, **kwargs):
    self.prompts_by_label[kwargs.get("trace_label")] = prompt
    return super().generate_json(prompt, **kwargs)


class CandidateChangeControlProvider(FakeControlProvider):
  def __init__(self):
    super().__init__()
    self._candidate_change_emitted = False

  def generate_json(self, prompt, **kwargs):
    trace_label = str(kwargs.get("trace_label") or "")
    if trace_label.startswith("dynamic_agent_") and not self._candidate_change_emitted:
      self._candidate_change_emitted = True
      return {
        "status": "completed",
        "summary": "Prepared CRM pipeline panel.",
        "recommendations": ["Include a pipeline panel."],
        "requirements": ["Show stage counts."],
        "risks": [],
        "candidate_changes": [
          {
            "path": "src/Pipeline.jsx",
            "content": "export default function Pipeline() { return <section>Pipeline</section>; }",
          }
        ],
      }
    return super().generate_json(prompt, **kwargs)


class FailingControlProvider:
  name = "failing-control"
  provider_role = CONTROL_PROVIDER_ROLE

  def generate_json(self, prompt, **kwargs):
    raise RuntimeError("Connection error.")


class ModelSupervisorControlProvider(FakeControlProvider):
  force_model_supervisor = True

  def __init__(self, *, invalid_supervisor_decision=False):
    self.invalid_supervisor_decision = invalid_supervisor_decision
    self.supervisor_calls = 0

  def generate_json(self, prompt, **kwargs):
    if kwargs.get("trace_label") == "supervisor_agent":
      self.supervisor_calls += 1
      if self.invalid_supervisor_decision:
        return {
          "next_agent": "Unsafe Agent",
          "next_action": "skip_validation_and_commit",
          "reason": "Invalid test decision.",
          "tools_to_call": ["WRITE_PROJECT_FILES"],
          "stop_or_continue": "continue",
        }
      available_actions = json.loads(prompt.split("Available actions: ", 1)[1].split("\n", 1)[0])
      selected = available_actions[0]
      return {
        "next_agent": selected["agent"],
        "next_action": selected["name"],
        "reason": "Model supervisor selected the next legal transition.",
        "tools_to_call": selected.get("tools", []),
        "stop_or_continue": "done" if selected["name"] == "DONE" else "continue",
      }
    return super().generate_json(prompt, **kwargs)


class MissingRequiredToolSupervisorControlProvider(ModelSupervisorControlProvider):
  def generate_json(self, prompt, **kwargs):
    if kwargs.get("trace_label") == "supervisor_agent":
      self.supervisor_calls += 1
      available_actions = json.loads(prompt.split("Available actions: ", 1)[1].split("\n", 1)[0])
      selected = available_actions[0]
      return {
        "next_agent": selected["agent"],
        "next_action": selected["name"],
        "reason": "Model supervisor selected the next legal transition but omitted required tools.",
        "tools_to_call": [],
        "stop_or_continue": "done" if selected["name"] == "DONE" else "continue",
      }
    return super().generate_json(prompt, **kwargs)


class FakeArtifactProvider:
  name = "fake-artifact"
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self):
    self.calls = []

  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    if kwargs.get("trace_label") == "scoped_update_artifact":
      return {
        "status": "completed",
        "summary": "Updated the approved existing source file.",
        "changed_files": [{"path": "src/App.jsx", "code": RAW_APP_CODE}],
        "preserved": ["All unrelated files"],
        "self_checks": ["Changed only src/App.jsx"],
        "clarification_question": "",
      }
    return valid_artifact(title=f"Artifact {len(self.calls)}")


class BugFixControlProvider(FakeControlProvider):
  def generate_json(self, prompt, **kwargs):
    if kwargs.get("trace_label") == "update_analysis_agent":
      return {
        "update_mode": "bug_fix",
        "request_kind": "bug_fix",
        "execution_strategy": "scoped_model_patch",
        "scope": "small",
        "summary": "Define the missing categories value used by the existing component.",
        "target_symbols": ["categories"],
        "candidate_files": ["src/App.jsx"],
        "required_agents": ["debug_patch_agent"],
        "preserve_rules": ["Preserve the existing component structure and unrelated behavior."],
        "allow_full_regeneration": False,
        "clarification_question": "",
        "reason": "The reported ReferenceError is a bounded existing-project bug.",
      }
    return super().generate_json(prompt, **kwargs)


class BugFixArtifactProvider(FakeArtifactProvider):
  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    if kwargs.get("trace_label") == "scoped_update_artifact":
      return {
        "status": "completed",
        "summary": "Defined the missing categories value.",
        "changed_files": [
          {
            "path": "src/App.jsx",
            "code": 'const categories = ["All"];\nexport default function App() { return <main>{categories.join(", ")}</main>; }',
          }
        ],
        "preserved": ["Existing component structure"],
        "self_checks": ["categories is defined before use"],
        "clarification_question": "",
      }
    return valid_artifact(title=f"Artifact {len(self.calls)}")


class CapturingArtifactProvider(FakeArtifactProvider):
  def __init__(self):
    super().__init__()
    self.prompts = []

  def generate_json(self, prompt, **kwargs):
    self.prompts.append(prompt)
    return super().generate_json(prompt, **kwargs)


class ReactApiArtifactProvider:
  name = "react-api-artifact"
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self):
    self.calls = []

  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    artifact = valid_artifact(title="React API Artifact")
    artifact["generated_website"]["files"] = [
      {
        "path": "src/App.jsx",
        "purpose": "Generated app.",
        "code": 'import { Card } from "./Card";\nexport default function App() { return <Card />; }',
      },
      {
        "path": "src/Card.js",
        "purpose": "Generated card.",
        "code": 'export const Card = () => React.createElement("article", null, "Fresh produce");',
      },
    ]
    return artifact


class ConnectionFailingArtifactProvider:
  name = "failing-artifact"
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self, message="Connection error."):
    self.calls = []
    self.message = message

  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    raise RuntimeError(self.message)


class InvalidJsonArtifactProvider:
  name = "invalid-json-artifact"
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self):
    self.calls = []

  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    raise RuntimeError('Gemini returned invalid JSON: {"generated_website": {"title": "Broken"')


class SlowArtifactProvider:
  name = "slow-artifact"
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self):
    self.calls = []

  def generate_json(self, prompt, **kwargs):
    self.calls.append(kwargs.get("trace_label"))
    time.sleep(2)
    return valid_artifact(title="Slow Artifact")


class FakeUser:
  id = "user-1"


def test_artifact_connection_fallback_is_not_used():
  assert not should_use_deterministic_artifact_fallback(RuntimeError("A model connection failed during generation."))


def test_gemini_json_parser_accepts_raw_multiline_scoped_patch_strings():
  parsed = parse_json_text(
    """```json
{
  "status": "completed",
  "summary": "Updated contact detail tabs.",
  "edits": [
    {
      "path": "src/components/ModulesView.jsx",
      "search": "const tabs = ['Customer'];
return <section>{tabs.join(', ')}</section>;",
      "replace": "const tabs = ['Customer', 'Activity'];
return <section>{tabs.join(', ')}</section>;",
      "expected_replacements": 1
    }
  ],
  "changed_files": [],
  "clarification_question": ""
}
```"""
  )

  assert parsed["status"] == "completed"
  assert parsed["edits"][0]["search"].splitlines()[1].startswith("return")


def test_runtime_timeout_seconds_uses_env_override(monkeypatch):
  monkeypatch.setenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "240")

  assert runtime_timeout_seconds() == 240


def test_artifact_soft_timeout_defaults_to_gemini_timeout(monkeypatch):
  monkeypatch.delenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", raising=False)
  monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "300")

  assert artifact_model_soft_timeout_seconds() == 300


def test_artifact_soft_timeout_can_be_disabled(monkeypatch):
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "0")
  monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "300")

  assert artifact_model_soft_timeout_seconds() == 0


def test_repair_model_soft_timeout_defaults_to_90(monkeypatch):
  monkeypatch.delenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", raising=False)

  assert repair_model_soft_timeout_seconds() == 90


def test_repair_model_soft_timeout_uses_env_override(monkeypatch):
  monkeypatch.setenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", "45")

  assert repair_model_soft_timeout_seconds() == 45


def test_scoped_update_uses_short_repair_model_timeout(monkeypatch):
  monkeypatch.setenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", "45")
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "300")

  assert artifact_call_soft_timeout_seconds("scoped_update_artifact") == 45
  assert artifact_call_soft_timeout_seconds("generate_website_artifact") == 300


def test_scoped_update_timeout_defaults_to_45(monkeypatch):
  monkeypatch.delenv("SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS", raising=False)
  monkeypatch.delenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", raising=False)
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "300")

  assert scoped_update_model_soft_timeout_seconds() == 45
  assert artifact_call_soft_timeout_seconds("scoped_update_artifact") == 45


def test_scoped_update_timeout_uses_explicit_override(monkeypatch):
  monkeypatch.setenv("SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS", "12")
  monkeypatch.setenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", "45")

  assert scoped_update_model_soft_timeout_seconds() == 12


def test_scoped_update_timeout_uses_repair_fallback(monkeypatch):
  monkeypatch.delenv("SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS", raising=False)
  monkeypatch.setenv("REPAIR_MODEL_SOFT_TIMEOUT_SECONDS", "300")

  assert scoped_update_model_soft_timeout_seconds() == 300


def test_scoped_update_sequence_timeout_defaults_to_30(monkeypatch):
  monkeypatch.delenv("SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS", raising=False)

  assert scoped_update_sequence_timeout_seconds() == 30


def test_scoped_update_sequence_timeout_uses_explicit_override(monkeypatch):
  monkeypatch.setenv("SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS", "9")

  assert scoped_update_sequence_timeout_seconds() == 9


def test_invalid_artifact_json_preserves_project_without_fallback():
  assert is_artifact_json_invalid_error(RuntimeError("Gemini returned invalid JSON: {"))
  assert not should_use_deterministic_artifact_fallback(RuntimeError("Gemini returned invalid JSON: {"))


def test_connection_reset_by_peer_is_model_connection_error():
  assert is_model_connection_error(ConnectionResetError(54, "Connection reset by peer"))


def test_update_summary_progress_describes_scope_before_editing():
  analysis = {
    "summary": "Rewrite onboarding as a 5-step chat flow with skip options",
    "update_mode": "feature_patch",
    "request_kind": "component_update",
    "execution_strategy": "scoped_model_patch",
    "scope": "medium",
    "reason": "Scoped change requires approved candidate files.",
    "candidate_files": ["src/components/OnboardingWizard.jsx", "src/App.jsx"],
    "candidate_new_files": [],
    "scoped_update_tasks": [
      {
        "id": "step_1",
        "summary": "Rewrite OnboardingWizard as the chat interface",
        "candidate_files": ["src/components/OnboardingWizard.jsx"],
      },
      {
        "id": "step_2",
        "summary": "Update App completion payload handling",
        "candidate_files": ["src/App.jsx"],
      },
    ],
  }

  message = update_request_summary_message(analysis)
  detail = update_request_summary_progress_detail(analysis)

  assert "I understood the update" in message
  assert "5-step chat flow" in message
  assert "I split it into 2 tasks" in message
  assert "src/components/OnboardingWizard.jsx" in message
  assert detail["task_count"] == 2
  assert detail["tasks"][0]["summary"] == "Rewrite OnboardingWizard as the chat interface"
  assert detail["selected_agent"] == "Scoped Update Agent"
  assert detail["selected_action"] == "RUN_SCOPED_UPDATE_AGENT"
  assert detail["decision_reason"] == "Scoped change requires approved candidate files."


def test_scoped_update_model_connection_error_becomes_guard_error():
  class ResetProvider:
    def generate_json(self, prompt, **kwargs):
      raise ConnectionResetError(54, "Connection reset by peer")

  with pytest.raises(ScopedUpdateGuardError) as exc_info:
    run_scoped_update_agent(
      ResetProvider(),
      prompt="Update the onboarding chat flow.",
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": [],
        "target_symbols": ["App"],
        "summary": "Update onboarding flow.",
      },
      existing_files=[
        {
          "path": "src/App.jsx",
          "content": "export default function App() { return <div>Onboarding</div>; }",
        }
      ],
      code_search_matches=[],
    )

  assert "could not reach the model provider" in str(exc_info.value)


def test_scoped_update_sequence_timeout_fails_before_preview_and_write(monkeypatch):
  monkeypatch.setenv("SCOPED_UPDATE_SEQUENCE_TIMEOUT_SECONDS", "1")
  monkeypatch.setenv("SCOPED_UPDATE_MODEL_SOFT_TIMEOUT_SECONDS", "10")
  tool_calls = []
  progress_events = []
  existing_files = [
    {
      "path": "package.json",
      "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}',
    },
    {
      "path": "index.html",
      "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>',
    },
    {
      "path": "src/main.jsx",
      "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);',
    },
    {
      "path": "src/App.jsx",
      "content": 'export default function App() { return <main>Old onboarding</main>; }',
    },
  ]

  def tool_executor(name, context, user, arguments):
    tool_calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool after scoped timeout: {name}")

  started_at = time.monotonic()
  with pytest.raises(ScopedUpdateGuardError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Update the onboarding page with a 5-step conversational chat flow",
      routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=SlowArtifactProvider(),
      prepared_sections={},
      tool_executor=tool_executor,
      emit_progress=lambda step, message, **kwargs: progress_events.append({"step": step, "message": message, **kwargs}),
      max_repair_attempts=0,
    )

  assert time.monotonic() - started_at < 1.8
  assert "Scoped update timed out" in str(exc_info.value)
  assert tool_calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]
  assert any(event["step"] == "agent.loop.run_scoped_update_agent.model_started" for event in progress_events)
  assert any(
    event["step"] == "agent.loop.run_scoped_update_agent.failed" and event.get("status") == "failed"
    for event in progress_events
  )


def test_onboarding_chat_scoped_patch_prioritizes_component_over_data_file():
  class NoModelPatchProvider:
    name = "no-model-patch"
    provider_role = ARTIFACT_PROVIDER_ROLE

    def __init__(self):
      self.calls = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      raise AssertionError("Known onboarding chat updates should use the deterministic scoped patch.")

  provider = NoModelPatchProvider()
  result = run_scoped_update_agent(
    provider,
    prompt="update the onboarding process with 5 steps and those things done in chat only ai chat",
    update_analysis={
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "medium",
      "summary": "Replace onboarding with a 5-step conversational AI chat interface.",
      "target_symbols": ["OnboardingWizard", "mockData"],
      "candidate_files": ["src/data/mockData.js", "src/components/OnboardingWizard.jsx"],
      "candidate_new_files": ["src/components/OnboardingChatWizard.jsx"],
      "feature_plan": {
        "name": "OnboardingChatWizard",
        "type": "component",
        "items": ["Chat UI", "5-step sequential flow"],
        "interaction": "User completes onboarding through AI chat.",
      },
    },
    existing_files=[
      {"path": "src/data/mockData.js", "content": "export const onboarding = [];"},
      {
        "path": "src/components/OnboardingWizard.jsx",
        "content": "export default function OnboardingWizard() { return <form>Old onboarding</form>; }",
      },
    ],
    code_search_matches=[],
  )

  assert provider.calls == []
  assert result["deterministic_fallback"] == "onboarding_chat_flow"
  assert result["changed_files"][0]["path"] == "src/components/OnboardingWizard.jsx"
  assert "Conversational onboarding chat" in result["changed_files"][0]["code"]


def test_vite_scaffold_normalization_adds_missing_files_and_preserves_existing():
  files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"}}'},
    {"path": "src/App.jsx", "content": NORMALIZED_APP_CODE},
  ]

  normalized, added_paths = ensure_vite_scaffold_files(files, title="Farm")

  assert added_paths == ["index.html", "src/main.jsx", "src/index.css", "tailwind.config.js", "postcss.config.js"]
  assert normalized[0] == files[0]
  assert normalized[1] == files[1]
  assert {file_item["path"] for file_item in normalized} >= {
    "package.json",
    "index.html",
    "src/main.jsx",
    "src/App.jsx",
    "src/index.css",
    "tailwind.config.js",
    "postcss.config.js",
  }


def test_frontend_runtime_import_normalization_shims_react_router_dom():
  files = [
    {
      "path": "src/App.jsx",
      "content": 'import { BrowserRouter, Routes, Route, Link } from "react-router-dom";\nexport default function App() { return <BrowserRouter><Link to="/about">About</Link><Routes><Route path="/" element={<main>Home</main>} /></Routes></BrowserRouter>; }',
    },
    {
      "path": "src/pages/About.jsx",
      "content": "export default function About() { return <main>About</main>; }",
    },
  ]

  normalized, changed_paths = normalize_frontend_runtime_imports(files)
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}

  assert changed_paths == ["src/App.jsx", "src/worktual-router-shim.jsx"]
  assert 'from "./worktual-router-shim.jsx"' in by_path["src/App.jsx"]
  assert "react-router-dom" not in by_path["src/App.jsx"]
  assert "export function BrowserRouter" in by_path["src/worktual-router-shim.jsx"]
  assert "export function Routes" in by_path["src/worktual-router-shim.jsx"]


def test_router_shim_supports_preview_navigation_and_outlets():
  code = router_shim_code()

  assert "const RouterContext = createContext(null)" in code
  assert "window.history[method]" in code
  assert "if (route === '/') return true" in code
  assert "export function Navigate({ to = '/', replace = true })" in code
  assert "navigate(to, { replace })" in code
  assert "export function Outlet()" in code
  assert "useContext(OutletContext)" in code
  assert "return router?.navigate || (() => {})" in code


def test_frontend_runtime_import_normalization_shims_unavailable_ui_helpers():
  files = [
    {
      "path": "src/components/Card.jsx",
      "content": (
        'import { motion, AnimatePresence } from "framer-motion";\n'
        'import clsx from "clsx";\n'
        'import { twMerge } from "tailwind-merge";\n'
        "export default function Card() {\n"
        "  return <AnimatePresence><motion.div className={twMerge(clsx('p-4', { shadow: true }))}>Ready</motion.div></AnimatePresence>;\n"
        "}\n"
      ),
    },
  ]

  normalized, changed_paths = normalize_frontend_runtime_imports(files)
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}

  assert changed_paths == [
    "src/components/Card.jsx",
    "src/worktual-framer-motion-shim.jsx",
    "src/worktual-clsx-shim.js",
    "src/worktual-tailwind-merge-shim.js",
  ]
  assert 'from "framer-motion"' not in by_path["src/components/Card.jsx"]
  assert 'from "tailwind-merge"' not in by_path["src/components/Card.jsx"]
  assert 'from "clsx"' not in by_path["src/components/Card.jsx"]
  assert 'from "../worktual-framer-motion-shim.jsx"' in by_path["src/components/Card.jsx"]
  assert 'from "../worktual-clsx-shim.js"' in by_path["src/components/Card.jsx"]
  assert 'from "../worktual-tailwind-merge-shim.js"' in by_path["src/components/Card.jsx"]
  assert "export const motion" in by_path["src/worktual-framer-motion-shim.jsx"]
  assert "export function AnimatePresence" in by_path["src/worktual-framer-motion-shim.jsx"]
  assert "export default clsx" in by_path["src/worktual-clsx-shim.js"]
  assert "export function twMerge" in by_path["src/worktual-tailwind-merge-shim.js"]


def test_preview_build_unresolved_runtime_import_reason_is_deterministic_repairable():
  reason = (
    "Build failed in 335ms error during build: [vite]: Rollup failed to resolve import "
    '"react-router-dom" from "/tmp/pending/src/App.jsx".'
  )

  assert is_unresolved_preview_runtime_import_reason(reason) is True
  assert is_unresolved_preview_runtime_import_reason("Build failed: missing ./local-module.js") is False


def test_tailwind_runtime_normalization_adds_missing_config_deps_and_directives():
  files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"}}'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": 'import React from "react";\nexport default function App() { return <main className="min-h-screen bg-gray-50 px-6 py-8">ok</main>; }',
    },
  ]

  normalized, changed_paths = ensure_tailwind_runtime_files(files)
  by_path = {file_item["path"]: file_item["content"] for file_item in normalized}
  package_json = json.loads(by_path["package.json"])

  assert changed_paths == ["package.json", "src/index.css", "tailwind.config.js", "postcss.config.js"]
  assert package_json["devDependencies"]["tailwindcss"]
  assert package_json["devDependencies"]["postcss"]
  assert package_json["devDependencies"]["autoprefixer"]
  assert by_path["src/index.css"].startswith("@tailwind base;\n@tailwind components;\n@tailwind utilities;")
  assert "Times New Roman" in by_path["src/index.css"]
  assert "module.exports" in by_path["tailwind.config.js"]
  assert "Times New Roman" in by_path["tailwind.config.js"]
  assert "tailwindcss" in by_path["postcss.config.js"]


def test_artifact_soft_timeout_worker_preserves_request_telemetry(monkeypatch):
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "2")
  captured_request_ids = []

  class Provider:
    def generate_json(self, prompt, **kwargs):
      context = current_telemetry_context()
      captured_request_ids.append(context.request_id if context else None)
      return {"ok": True}

  with telemetry_scope(RunTelemetryContext.create(request_id="request-telemetry")):
    result = run_artifact_provider_with_soft_timeout(Provider(), "prompt", trace_label="test")

  assert result == {"ok": True}
  assert captured_request_ids == ["request-telemetry"]


def test_runtime_timeout_allows_post_qa_finalization_only():
  incomplete_state = {
    "files": valid_artifact()["generated_website"]["files"],
    "validation_result": {"status": "valid"},
    "preview": {"status": "ready"},
    "visual_qa_result": None,
    "completed": False,
    "tool_calls": [],
  }
  with pytest.raises(AgentRuntimeLoopError):
    enforce_loop_budget(incomplete_state, start_time=time.monotonic() - 10, timeout_seconds=1, max_tool_calls=18)

  finalization_state = {
    **incomplete_state,
    "visual_qa_result": {"status": "passed"},
  }
  enforce_loop_budget(finalization_state, start_time=time.monotonic() - 10, timeout_seconds=1, max_tool_calls=18)

  assert finalization_state["runtime_budget_finalization_grace_used"] is True


def test_mas_commit_gate_blocks_write_before_validation_preview_and_qa():
  state = {
    "validation_result": {},
    "preview_result": {},
    "visual_qa_result": {},
  }

  with pytest.raises(MASContractError, match="MAS commit gate blocked WRITE_PROJECT_FILES"):
    assert_mas_action_allowed(state, "WRITE_PROJECT_FILES")

  state["validation_result"] = {"status": "valid"}
  state["preview_result"] = {"version": {"status": "ready"}}
  state["visual_qa_result"] = {"status": "passed"}

  assert_mas_action_allowed(state, "WRITE_PROJECT_FILES")


def test_real_agent_runtime_executes_backend_tools_as_source_of_truth():
  reset_global_agent_registry()
  calls = []
  staged_files = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      staged_files.extend(arguments["files"])
      assert {file_item["path"] for file_item in arguments["files"]} >= {"package.json", "index.html", "src/main.jsx", "src/App.jsx", "src/index.css"}
      assert next(file_item["content"] for file_item in arguments["files"] if file_item["path"] == "src/App.jsx") == NORMALIZED_APP_CODE
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments["key"]}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=FakeArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  write_calls = [name for name in calls if name == "WRITE_PROJECT_FILES"]
  assert_bootstrap_tool_calls(calls)
  assert write_calls, "Expected incremental workspace writes before validation"
  assert calls.index(write_calls[0]) < calls.index("VALIDATE_PROJECT_ARTIFACT")
  assert "WRITE_PROJECT_FILES" not in calls[calls.index("RUN_PREVIEW_VISUAL_QA") + 1 :]
  assert calls[-1] == "PERSIST_PROJECT_MEMORY"
  assert result["runtime"]["tool_source_of_truth"] is True
  assert result["runtime"]["supervisor_decisions"]
  assert result["runtime"]["final_output"]["preview_status"] == "ready"
  assert result["runtime"]["execution_mode"] == "dynamic_supervisor_loop"
  assert result["runtime"]["action_history"] == generation_action_history()
  assert result["state"]["dynamic_workflow_plan"]["planning_source"] == "model_routed_direct_generation_policy"
  assert result["state"]["dynamic_specialist_results"]["status"] == "skipped"
  assert result["state"]["ux_review"]["status"] == "skipped"
  assert result["state"]["accessibility_review"]["status"] == "skipped"
  assert result["state"]["dynamic_patch_integrated"] is True
  mas_runtime = result["runtime"]["mas_runtime"]
  assert mas_runtime["runtime"] == "worktual-mas-runtime"
  assert mas_runtime["status"] == "completed"
  assert mas_runtime["step_count"] == len(result["runtime"]["action_history"])
  assert mas_runtime["handoff_count"] == mas_runtime["step_count"] - 1
  assert mas_runtime["completion_gates"] == {
    "artifact_valid": True,
    "staged_preview_ready": True,
    "visual_qa_passed": True,
    "files_committed": True,
    "memory_persisted": True,
  }
  assert_bootstrap_mas_step(mas_runtime["steps"][0])
  assert mas_runtime["steps"][-1]["action"] == "PERSIST_PROJECT_MEMORY"


def test_real_agent_runtime_adds_tailwind_runtime_before_preview():
  reset_global_agent_registry()
  staged_files = []

  class TailwindArtifactProvider:
    name = "tailwind-artifact"
    provider_role = ARTIFACT_PROVIDER_ROLE

    def generate_json(self, prompt, **kwargs):
      artifact = valid_artifact(title="Tailwind Shop")
      artifact["generated_website"]["files"] = [
        {
          "path": "src/App.jsx",
          "purpose": "Tailwind generated app.",
          "code": 'export default function App() { return <main className="min-h-screen bg-gray-50 px-6 py-8"><section className="grid gap-4">Shop</section></main>; }',
        }
      ]
      return artifact

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {
        "status": "valid",
        "file_count": len(arguments["generated_website"]["files"]),
        "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]],
      }
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      staged_files.extend(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      package_json = json.loads(by_path["package.json"])
      assert {"tailwind.config.js", "postcss.config.js", "src/index.css", "src/main.jsx", "index.html"} <= set(by_path)
      assert by_path["src/index.css"].startswith("@tailwind base;\n@tailwind components;\n@tailwind utilities;")
      assert package_json["devDependencies"]["tailwindcss"]
      assert by_path["src/App.jsx"].startswith('import React from "react";')
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments["key"]}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate an e-commerce website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=TailwindArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert result["runtime"]["completion_proof"]["satisfied"] is True
  assert {file_item["path"] for file_item in staged_files} >= {"tailwind.config.js", "postcss.config.js", "src/index.css"}
  assert result["runtime"]["completion_status"] == {
    "files_exist": True,
    "artifact_valid": True,
    "staged_preview_ready": True,
    "visual_qa_passed": True,
    "files_committed": True,
    "memory_prepared": True,
  }


def test_real_agent_runtime_shims_react_router_before_preview():
  reset_global_agent_registry()
  staged_files = []

  class RouterArtifactProvider:
    name = "router-artifact"
    provider_role = ARTIFACT_PROVIDER_ROLE

    def generate_json(self, prompt, **kwargs):
      artifact = valid_artifact(title="Router Site")
      artifact["generated_website"]["files"] = [
        {
          "path": "src/App.jsx",
          "purpose": "Generated app with router import.",
          "code": (
            'import { BrowserRouter, Routes, Route, Link } from "react-router-dom";\n'
            'export default function App() { return <BrowserRouter><Link to="/about">About</Link><Routes><Route path="/" element={<main>Home</main>} /></Routes></BrowserRouter>; }'
          ),
        }
      ]
      return artifact

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {
        "status": "valid",
        "file_count": len(arguments["generated_website"]["files"]),
        "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]],
      }
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      staged_files.extend(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "react-router-dom" not in by_path["src/App.jsx"]
      assert 'from "./worktual-router-shim.jsx"' in by_path["src/App.jsx"]
      assert "export function BrowserRouter" in by_path["src/worktual-router-shim.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments["key"]}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a routed marketing website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=RouterArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert result["runtime"]["completion_proof"]["satisfied"] is True
  assert {file_item["path"] for file_item in staged_files} >= {"src/worktual-router-shim.jsx"}
  assert any(
    step["action"] == "normalize_frontend_runtime_imports_before_preview"
    for step in result["runtime"]["steps"]
  )


def test_dynamic_candidate_change_is_integrated_before_validation_and_commit(monkeypatch):
  monkeypatch.setenv("ENABLE_FULL_DYNAMIC_GENERATION", "true")
  validated_paths = []
  staged_files = []
  committed_files = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      validated_paths.extend(item["path"] for item in arguments["generated_website"]["files"])
      return {"status": "valid", "file_count": len(validated_paths), "paths": validated_paths}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      staged_files.extend(arguments["files"])
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/preview"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      committed_files.extend(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=CandidateChangeControlProvider(),
    artifact_provider=FakeArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert "RUN_DYNAMIC_PATCH_INTEGRATOR" in result["runtime"]["action_history"]
  assert "src/Pipeline.jsx" in validated_paths
  assert any(item["path"] == "src/Pipeline.jsx" and item["content"].startswith('import React from "react";') for item in staged_files)
  assert any(item["path"] == "src/Pipeline.jsx" for item in committed_files)
  assert result["runtime"]["candidate_change_summary"]["integration_status"] == "completed"


def test_code_agent_compacts_dynamic_specialist_context_before_artifact_call(monkeypatch):
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "0")
  provider = CapturingArtifactProvider()
  huge_summary = "Specialist detail. " * 6000

  run_code_agent(
    provider,
    prompt="Generate an e-commerce website",
    operation="generate",
    brief={"business_type": "e-commerce"},
    plan={"sections": ["Catalog", "Cart", "Checkout"]},
    prepared_sections={
      "dynamic_specialist_results": {
        "status": "completed",
        "completed_task_ids": ["checkout_flow"],
        "results": {
          "checkout_flow": {
            "agent": "Checkout Flow Agent",
            "agent_id": "checkout_flow_agent",
            "status": "completed",
            "source": "dynamic_agent",
            "summary": huge_summary,
            "recommendations": [huge_summary],
            "requirements": [huge_summary],
            "risks": [huge_summary],
          }
        },
      }
    },
    read_result={"files": []},
    memory_result={"memories": []},
    previous_error=None,
  )

  assert provider.calls == ["generate_website_artifact"]
  assert huge_summary not in provider.prompts[0]
  assert len(provider.prompts[0]) < 60000


def test_prompt_analyst_and_planner_compact_large_file_and_memory_context():
  provider = CapturingControlProvider()
  huge_file = "export default function App() { return <main>Huge</main>; }\n" * 4000
  huge_memory = "Previous generated artifact and runtime summary. " * 5000
  read_result = {"files": [{"path": "src/App.jsx", "content": huge_file}], "file_count": 1}
  memory_result = {
    "memories": [
      {
        "namespace": "agent",
        "key": "latest_generation",
        "kind": "summary",
        "content": huge_memory,
      }
    ],
    "memory_count": 1,
  }

  brief = run_prompt_analyst_agent(
    provider,
    "Generate an e-commerce website",
    {"intent": "website_generation", "next_action": "generate_website"},
    read_result,
    memory_result,
  )
  run_planner_agent(provider, "Generate an e-commerce website", brief, {}, memory_result)

  analyst_prompt = provider.prompts_by_label["prompt_analyst_agent"]
  planner_prompt = provider.prompts_by_label["planner_agent"]
  assert huge_file not in analyst_prompt
  assert huge_memory not in analyst_prompt
  assert huge_memory not in planner_prompt
  assert len(analyst_prompt) < 20000
  assert len(planner_prompt) < 25000


def test_real_agent_runtime_preserves_project_for_model_connection_error():
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool: {name}")

  artifact_provider = ConnectionFailingArtifactProvider()
  with pytest.raises(AgentRuntimeLoopError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate the website for farm website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FailingControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert "Code artifact validation failed: Connection error." in str(exc_info.value)
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_real_agent_runtime_preserves_project_for_invalid_gemini_json_without_repair():
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool: {name}")

  artifact_provider = InvalidJsonArtifactProvider()
  with pytest.raises(AgentRuntimeLoopError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate the website for farm website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert "Gemini returned invalid JSON" in str(exc_info.value)
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_real_agent_runtime_preserves_project_after_artifact_soft_timeout(monkeypatch):
  monkeypatch.setenv("ARTIFACT_MODEL_SOFT_TIMEOUT_SECONDS", "1")
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool: {name}")

  artifact_provider = SlowArtifactProvider()
  started_at = time.monotonic()
  with pytest.raises(AgentRuntimeLoopError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate the website for farm website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FailingControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert time.monotonic() - started_at < 1.8
  assert artifact_provider.calls == ["generate_website_artifact"]
  assert "Artifact model call timed out" in str(exc_info.value)
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_real_agent_runtime_normalizes_react_api_source_before_preview_without_repair():
  artifact_provider = ReactApiArtifactProvider()
  staged_files = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 2, "paths": ["src/App.jsx", "src/Card.js"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      staged_files.extend(arguments["files"])
      card = next(file_item for file_item in arguments["files"] if file_item["path"] == "src/Card.js")
      assert card["content"].startswith('import React from "react";\n')
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "build_log": "built", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate the website for farm website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert result["runtime"]["completion_proof"]["satisfied"] is True


def test_real_agent_runtime_preserves_project_when_no_spec_generation_artifact_fails():
  artifact_provider = ConnectionFailingArtifactProvider()
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {
        "project_id": arguments["project_id"],
        "memories": [{"content": "Prompt: Generate the website for e-commerce"}],
        "memory_count": 1,
      }
    raise AssertionError(f"Unexpected tool: {name}")

  with pytest.raises(AgentRuntimeLoopError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="I don't have any specific idea so start the generation",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "use defaults"},
      control_provider=FailingControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert "Code artifact validation failed: Connection error." in str(exc_info.value)
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_model_backed_supervisor_decisions_are_used_when_valid():
  control_provider = ModelSupervisorControlProvider()

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=control_provider,
    artifact_provider=FakeArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert control_provider.supervisor_calls >= 6
  assert {decision["decision_source"] for decision in result["runtime"]["supervisor_decisions"]} == {"model"}
  assert result["runtime"]["supervisor_policy_fallbacks"] == []
  assert len(result["runtime"]["supervisor_audit_trail"]) == len(result["runtime"]["supervisor_decisions"])
  assert result["runtime"]["supervisor_audit_trail"][0]["decision_source"] == "model"
  assert result["runtime"]["supervisor_audit_trail"][0]["legal_actions"] == [BOOTSTRAP_ACTION]
  assert result["runtime"]["supervisor_audit_trail"][0]["selected_required_tools"] == BOOTSTRAP_TOOLS
  assert result["runtime"]["completion_proof"]["satisfied"] is True
  assert result["runtime"]["final_output"]["completion_proof_satisfied"] is True


def test_invalid_model_supervisor_decisions_fall_back_to_policy():
  control_provider = ModelSupervisorControlProvider(invalid_supervisor_decision=True)

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=control_provider,
    artifact_provider=FakeArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert control_provider.supervisor_calls >= 6
  assert {decision["decision_source"] for decision in result["runtime"]["supervisor_decisions"]} == {"policy_fallback"}
  assert result["runtime"]["supervisor_policy_fallbacks"]


def test_supervisor_missing_required_tools_falls_back_with_audit_reason():
  control_provider = MissingRequiredToolSupervisorControlProvider()

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=control_provider,
    artifact_provider=FakeArtifactProvider(),
    prepared_sections={},
    tool_executor=tool_executor,
  )

  first_audit = result["runtime"]["supervisor_audit_trail"][0]
  assert first_audit["decision_source"] == "policy_fallback"
  assert first_audit["selected_action"] == BOOTSTRAP_ACTION
  assert first_audit["selected_action_is_legal"] is True
  assert first_audit["selected_required_tools"] == BOOTSTRAP_TOOLS
  assert first_audit["selected_tools_to_call"] == BOOTSTRAP_TOOLS
  assert first_audit["model_output"]["tools_to_call"] == []
  assert "required backend tools" in first_audit["guardrail_reason"]
  assert result["runtime"]["supervisor_policy_fallbacks"][0]["audit_id"] == first_audit["audit_id"]
  assert result["runtime"]["completion_proof"]["satisfied"] is True


def test_generation_continues_when_local_gpt_control_plane_is_down():
  artifact_provider = FakeArtifactProvider()
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate the website for farm website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FailingControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert_incremental_write_before_preview_calls(calls)
  assert result["runtime"]["completion_status"] == {
    "files_exist": True,
    "artifact_valid": True,
    "staged_preview_ready": True,
    "visual_qa_passed": True,
    "files_committed": True,
    "memory_prepared": True,
  }
  assert result["state"]["brief"]["control_fallback"]["source"] == "deterministic_prompt_analyst"
  assert result["state"]["plan"]["control_fallback"]["source"] == "deterministic_planner"
  assert result["state"]["ux_review"]["control_fallback"]["source"] == "model_routed_direct_generation_policy"
  assert result["state"]["accessibility_review"]["control_fallback"]["source"] == "model_routed_direct_generation_policy"
  assert {decision["decision_source"] for decision in result["runtime"]["supervisor_decisions"]} == {"policy"}
  assert result["runtime"]["supervisor_policy_fallbacks"] == []


def test_update_runtime_merges_changed_files_with_existing_snapshot_before_commit():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  written_files = []
  validated_files = []
  existing_files = [
    {
      "path": "package.json",
      "content": '{"type":"module","scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest","lucide-react":"latest"}}',
    },
    {
      "path": "src/App.jsx",
      "content": "export default function App() { return <main>old farm site</main>; }",
    },
    {
      "path": "src/styles.css",
      "content": "main { color: green; }",
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      validated_files.append(arguments["generated_website"]["files"])
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"]), "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Update the farm website hero title and CTA",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["scoped_update_artifact"]
  assert result["runtime"]["update_analysis"]["execution_strategy"] == "scoped_model_patch"
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert "RUN_DYNAMIC_AGENT_PLANNER" not in result["runtime"]["action_history"]
  assert "RUN_DYNAMIC_SPECIALISTS" not in result["runtime"]["action_history"]
  assert "RUN_UX_REVIEW_AGENT" not in result["runtime"]["action_history"]
  assert "RUN_ACCESSIBILITY_AGENT" not in result["runtime"]["action_history"]
  assert result["runtime"]["branch"] == "website_update"
  assert result["runtime"]["operation"] == "update"
  assert result["runtime"]["final_output"]["intent"] == "website_update"
  assert result["runtime"]["final_output"]["changed_file_paths"] == ["src/App.jsx"]
  assert len(preview_files) == 1
  preview_by_path = {file_item["path"]: file_item["content"] for file_item in preview_files[0]}
  assert preview_by_path["package.json"] == existing_files[0]["content"]
  assert preview_by_path["src/App.jsx"] == NORMALIZED_APP_CODE
  assert preview_by_path["src/styles.css"] == existing_files[2]["content"]
  assert {file_item["path"] for file_item in preview_files[0]} >= {"package.json", "index.html", "src/main.jsx", "src/App.jsx", "src/index.css", "src/styles.css"}
  assert_written_files_match_preview(written_files, preview_files)
  validated_paths = [file_item["path"] for file_item in validated_files[0]]
  assert "package.json" in validated_paths
  assert "src/App.jsx" in validated_paths
  assert "src/styles.css" in validated_paths


def test_runtime_error_uses_only_scoped_debug_patch_before_validation_and_commit():
  artifact_provider = BugFixArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Store</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": 'export default function App() { return <main>{categories.join(", ")}</main>; }'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert 'const categories = ["All"];' in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Fix ReferenceError: categories is not defined. The website is not opening.",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=BugFixControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["scoped_update_artifact"]
  assert result["runtime"]["action_history"] == scoped_update_action_history()
  assert result["runtime"]["update_analysis"]["update_mode"] == "bug_fix"
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert result["runtime"]["execution_mode"] == "model_selected_scoped_update_loop"
  assert "UX Review Agent" not in {agent["name"] for agent in result["runtime"]["agents"]}
  assert "Accessibility Agent" not in {agent["name"] for agent in result["runtime"]["agents"]}
  assert written_files


def test_undefined_name_runtime_error_uses_deterministic_fix_without_model_call():
  class UndefinedNameControlProvider(FakeControlProvider):
    def generate_json(self, prompt, **kwargs):
      if kwargs.get("trace_label") == "update_analysis_agent":
        return {
          "update_mode": "bug_fix",
          "request_kind": "bug_fix",
          "execution_strategy": "scoped_model_patch",
          "scope": "small",
          "summary": "Guard the dashboard setup config before reading its name.",
          "target_symbols": ["config", "Dashboard", "name"],
          "candidate_files": ["src/App.jsx", "src/components/Dashboard.jsx"],
          "required_agents": ["debug_patch_agent"],
          "preserve_rules": ["Preserve the existing dashboard and onboarding flow."],
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "The reported undefined .name crash is a bounded data-shape bug.",
        }
      return super().generate_json(prompt, **kwargs)

  class NoModelPatchArtifactProvider:
    name = "no-model-patch-artifact"
    provider_role = ARTIFACT_PROVIDER_ROLE

    def __init__(self):
      self.calls = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      raise AssertionError("Undefined .name runtime fix should not call the artifact model.")

  artifact_provider = NoModelPatchArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": (
        'import React, { useState } from "react";\n'
        'import Dashboard from "./components/Dashboard.jsx";\n\n'
        "export default function App() {\n"
        '  const [view, setView] = useState("dashboard");\n'
        "  const [config, setConfig] = useState(null);\n"
        '  return view === "dashboard" ? <Dashboard config={config} /> : <main />;\n'
        "}\n"
      ),
    },
    {
      "path": "src/components/Dashboard.jsx",
      "content": "export default function Dashboard({ config }) { return <h1>{config.name}</h1>; }",
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      by_path = {item["path"]: item["code"] for item in arguments["generated_website"]["files"]}
      assert "DEFAULT_CONFIG" in by_path["src/App.jsx"]
      assert "config={config || DEFAULT_CONFIG}" in by_path["src/App.jsx"]
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "useState(DEFAULT_CONFIG)" in by_path["src/App.jsx"]
      assert "config={config || DEFAULT_CONFIG}" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Uncaught TypeError: Cannot read properties of undefined (reading 'name') at Dashboard.jsx",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "runtime error"},
    control_provider=UndefinedNameControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert result["runtime"]["action_history"][:4] == scoped_update_action_prefix()
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert written_files


def test_scoped_update_retries_once_after_rewrite_too_much_guard():
  class OversizedThenExactEditArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      scoped_calls = self.calls.count("scoped_update_artifact")
      if scoped_calls == 1:
        return {
          "status": "completed",
          "summary": "Returned too much code.",
          "changed_files": [
            {
              "path": "src/App.jsx",
              "code": 'import React from "react";\nexport default function App() { return <main>'
              + ("Rebuilt notification dashboard " * 120)
              + "</main>; }",
            }
          ],
          "edits": [],
          "clarification_question": "",
        }
      return {
        "status": "completed",
        "summary": "Added empty notification data only.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "const notificationItems = [];",
            "replace": (
              "const notificationItems = [\n"
              "    { id: 1, title: 'No notifications yet', description: 'Empty notification data is ready for future alerts.' },\n"
              "  ];"
            ),
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = OversizedThenExactEditArtifactProvider()
  written_files = []
  app_code = (
    'import React from "react";\n'
    "export default function App() {\n"
    "  const notificationItems = [];\n"
    "  const dashboardCards = ['Revenue', 'Tasks', 'Inbox', 'Alerts'];\n"
    "  return (\n"
    "    <main>\n"
    "      <button aria-label=\"Notifications\">Bell</button>\n"
    "      <section>{notificationItems.length} notifications</section>\n"
    "      {dashboardCards.map((card) => <article key={card}>{card}</article>)}\n"
    "      <footer>Existing layout must stay untouched</footer>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": app_code},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "No notifications yet" in by_path["src/App.jsx"]
      assert "Existing layout must stay untouched" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Update the bell icon click behavior and provide empty notification data.",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 2
  assert "previous scoped patch failed" in artifact_provider.prompts[-1].lower()
  assert "do not return a complete changed_files replacement" in artifact_provider.prompts[-1]
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert result["runtime"]["repair_attempts"] == 1
  assert written_files


def test_scoped_update_retries_runtime_after_empty_blocked_patch_response():
  class EmptyBlockedThenExactEditArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      scoped_calls = self.calls.count("scoped_update_artifact")
      if scoped_calls <= 2:
        return {
          "status": "blocked",
          "summary": "No safe patch was returned.",
          "edits": [],
          "changed_files": [],
          "clarification_question": "",
        }
      return {
        "status": "completed",
        "summary": "Added empty notification data only.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "const notificationItems = [];",
            "replace": (
              "const notificationItems = [\n"
              "    { id: 1, title: 'No notifications yet', description: 'Empty notification data is ready for future alerts.' },\n"
              "  ];"
            ),
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = EmptyBlockedThenExactEditArtifactProvider()
  written_files = []
  app_code = (
    'import React from "react";\n'
    "export default function App() {\n"
    "  const notificationItems = [];\n"
    "  return <main>{notificationItems.length} notifications</main>;\n"
    "}\n"
  )
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": app_code},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "No notifications yet" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Update the bell icon click behavior and provide empty notification data.",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 3
  assert "returned no usable edits or changed_files" in artifact_provider.prompts[1]
  assert "previous scoped patch failed" in artifact_provider.prompts[2].lower()
  assert result["runtime"]["repair_attempts"] == 1
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert written_files


def test_scoped_update_falls_back_for_new_project_modal_no_patch():
  class EmptyNewProjectPatchProvider(FakeArtifactProvider):
    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      return {
        "status": "blocked",
        "summary": "No safe patch was returned.",
        "edits": [],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = EmptyNewProjectPatchProvider()
  written_files = []
  app_code = (
    'import React from "react";\n'
    "export default function App() {\n"
    "  return (\n"
    "    <main>\n"
    "      <button type=\"button\" className=\"primary\">+ New Project</button>\n"
    "      <section>Projects list</section>\n"
    "    </main>\n"
    "  );\n"
    "}\n"
  )
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": app_code},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "setIsNewProjectModalOpen(true)" in by_path["src/App.jsx"]
      assert "Create New Project" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="In project module + New project button is not working",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert written_files
  written_app = next(item["content"] for item in written_files[-1] if item["path"] == "src/App.jsx")
  assert "setIsNewProjectModalOpen(true)" in written_app
  assert "Create New Project" in written_app


def test_scoped_update_retries_source_context_clarification_from_approved_file():
  class SourceQuestionThenExactEditArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      scoped_calls = self.calls.count("scoped_update_artifact")
      if scoped_calls == 1:
        return {
          "status": "needs_clarification",
          "summary": "Need source segment.",
          "edits": [],
          "changed_files": [],
          "clarification_question": (
            "Could you please provide the JSX code segment from `src/components/ModulesView.jsx` "
            "where the leads/contacts list is rendered?"
          ),
        }
      return {
        "status": "completed",
        "summary": "Added contact click behavior.",
        "edits": [
          {
            "path": "src/components/ModulesView.jsx",
            "search": "<button>Initial Contact</button>",
            "replace": "<button onClick={() => setSelectedContact('initial')}>Initial Contact</button>",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = SourceQuestionThenExactEditArtifactProvider()
  update_analysis = {
    "update_mode": "feature_patch",
    "candidate_files": ["src/components/ModulesView.jsx"],
    "candidate_new_files": [],
    "target_symbols": ["Initial Contact"],
    "summary": "Open contact detail when the initial contact is clicked.",
  }
  existing_files = [
    {
      "path": "src/components/ModulesView.jsx",
      "content": (
        'import React, { useState } from "react";\n'
        "export default function ModulesView() {\n"
        "  const [selectedContact, setSelectedContact] = useState(null);\n"
        "  return <section><button>Initial Contact</button></section>;\n"
        "}\n"
      ),
    }
  ]

  response = run_scoped_update_agent(
    artifact_provider,
    prompt="When clicking the initial contact, open a detail page.",
    update_analysis=update_analysis,
    existing_files=existing_files,
    code_search_matches=[
      {
        "path": "src/components/ModulesView.jsx",
        "snippets": ["return <section><button>Initial Contact</button></section>;"],
      }
    ],
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 2
  assert "returned no usable edits or changed_files" in artifact_provider.prompts[1]
  changed_files = validate_scoped_update_changes(
    response,
    update_analysis=update_analysis,
    existing_files=existing_files,
  )
  assert "setSelectedContact('initial')" in changed_files[0]["content"]


def test_scoped_update_source_context_question_is_no_patch_guard_not_user_clarification():
  with pytest.raises(ScopedUpdateGuardError, match="no scoped edits or changed files"):
    validate_scoped_update_changes(
      {
        "status": "needs_clarification",
        "summary": "Need source segment.",
        "edits": [],
        "changed_files": [],
        "clarification_question": (
          "Could you please provide the JSX code segment from `src/components/ModulesView.jsx` "
          "where the leads/contacts list is rendered?"
        ),
      },
      update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/ModulesView.jsx"]},
      existing_files=[
        {
          "path": "src/components/ModulesView.jsx",
          "content": "export default function ModulesView() { return <button>Initial Contact</button>; }\n",
        }
      ],
    )


def test_scoped_update_top_of_file_question_is_no_patch_guard_not_user_clarification():
  with pytest.raises(ScopedUpdateGuardError, match="no scoped edits or changed files"):
    validate_scoped_update_changes(
      {
        "status": "needs_clarification",
        "summary": "Need file setup.",
        "edits": [],
        "changed_files": [],
        "clarification_question": (
          "I need the top of src/App.jsx to add the import for SupportModal and the state variables "
          "(supportModalOpen, supportTopic) required to wire the footer links. The current excerpts "
          "only show the footer. Could you provide the top of the file?"
        ),
      },
      update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/App.jsx"]},
      existing_files=[
        {
          "path": "src/App.jsx",
          "content": "export default function App() { return <footer><button>Support us</button></footer>; }\n",
        }
      ],
    )


def test_scoped_update_table_snippet_question_is_no_patch_guard_not_user_clarification():
  with pytest.raises(ScopedUpdateGuardError, match="no scoped edits or changed files"):
    validate_scoped_update_changes(
      {
        "status": "needs_clarification",
        "summary": "Need table snippet.",
        "edits": [],
        "changed_files": [],
        "clarification_question": (
          "I need to update the lead/contact table rows in the 'module-lead' view to be clickable, "
          "but the provided snippets do not include the table rendering code for the 'module-lead' view. "
          "Could you provide the snippet containing the table rows for leads?"
        ),
      },
      update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/ModulesView.jsx"]},
      existing_files=[
        {
          "path": "src/components/ModulesView.jsx",
          "content": "export default function ModulesView() { return <table><tbody /></table>; }\n",
        }
      ],
    )


def test_update_code_search_includes_lead_table_render_context():
  content = (
    "export default function ModulesView() {\n"
    "  const leads = [{ id: 'l1', name: 'Initial Contact', company: 'Acme' }];\n"
    "  return (\n"
    "    <section id=\"module-lead\">\n"
    "      <table className=\"lead-table\">\n"
    "        <tbody>\n"
    "          {leads.map((lead) => (\n"
    "            <tr key={lead.id} className=\"lead-row\">\n"
    "              <td>{lead.name}</td>\n"
    "              <td>{lead.company}</td>\n"
    "            </tr>\n"
    "          ))}\n"
    "        </tbody>\n"
    "      </table>\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )

  matches = build_update_code_search_matches(
    "Make lead contact table rows clickable in module-lead",
    [{"path": "src/components/ModulesView.jsx", "content": content}],
  )
  snippets = " ".join(matches[0]["snippets"])

  assert "leads.map" in snippets
  assert "<tr key={lead.id}" in snippets
  assert "module-lead" in snippets


def test_scoped_update_rejects_unapproved_file_change():
  with pytest.raises(ScopedUpdateGuardError, match="unapproved file"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "changed_files": [{"path": "src/Other.jsx", "code": "export default function Other() { return null; }"}],
      },
      update_analysis={"update_mode": "bug_fix", "candidate_files": ["src/App.jsx"]},
      existing_files=[
        {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
        {"path": "src/Other.jsx", "content": "export default function Other() { return <p>Keep</p>; }"},
      ],
    )


def test_scoped_feature_update_allows_approved_new_component_file():
  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "edits": [
        {
          "path": "src/App.jsx",
          "search": "export default function App() { return <main>Dashboard</main>; }",
          "replace": 'import AIChatWidget from "./components/AIChatWidget.jsx";\nexport default function App() { return <main>Dashboard<AIChatWidget /></main>; }',
          "expected_replacements": 1,
        }
      ],
      "changed_files": [
        {
          "path": "src/components/AIChatWidget.jsx",
          "code": "export default function AIChatWidget() { return <aside>AI assistant ready</aside>; }\n",
        }
      ],
      "clarification_question": "",
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/App.jsx"],
      "candidate_new_files": ["src/components/AIChatWidget.jsx"],
    },
    existing_files=[
      {
        "path": "src/App.jsx",
        "content": "export default function App() { return <main>Dashboard</main>; }",
      }
    ],
  )

  assert [item["path"] for item in changed] == ["src/App.jsx", "src/components/AIChatWidget.jsx"]


def test_update_analysis_infers_candidate_new_file_for_feature_patch():
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Add an AI chat widget.",
      "candidate_files": ["src/App.jsx"],
      "candidate_new_files": [],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/App.jsx"],
    code_search_matches=[],
    user_prompt="Add AI chat widget to the dashboard",
  )

  assert result["candidate_new_files"] == ["src/components/AIChatWidget.jsx"]
  assert result["required_agents"][0] == "new_file_requirement_agent"
  assert result["new_file_requirements"]["needed"] is True
  planned = result["new_file_requirements"]["planned_files"][0]
  assert planned["path"] == "src/components/AIChatWidget.jsx"
  assert planned["integration_file"] == "src/App.jsx"
  assert planned["import_name"] == "AIChatWidget"
  assert planned["import_path_from_integration"] == "./components/AIChatWidget"


def test_update_analysis_infers_candidate_new_page_and_component_paths():
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Open a rich contact detail page.",
      "feature_plan": {
        "name": "ContactDetailPage",
        "type": "page",
        "items": ["Customer", "Activity"],
        "interaction": "Open when clicking a contact.",
      },
      "candidate_files": ["src/components/ModulesView.jsx"],
      "candidate_new_files": [],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/components/ModulesView.jsx"],
    code_search_matches=[],
    user_prompt="When clicking contacts open a rich contact detail page with customer and activity tabs",
  )

  assert result["candidate_new_files"] == [
    "src/pages/ContactDetailPage.jsx",
    "src/components/ContactDetailPage.jsx",
  ]
  assert result["new_file_requirements"]["needed"] is True
  assert result["new_file_requirements"]["verification"]["integration_files_valid"] is True
  assert [item["integration_file"] for item in result["new_file_requirements"]["planned_files"]] == [
    "src/components/ModulesView.jsx",
    "src/components/ModulesView.jsx",
  ]


def test_update_analysis_preserves_model_selected_existing_page_update():
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Update the onboarding page.",
      "candidate_files": ["src/components/OnboardingWizard.jsx"],
      "candidate_new_files": [],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/components/OnboardingWizard.jsx"],
    code_search_matches=[],
    user_prompt="update the onboarding page",
  )

  assert result["update_mode"] == "feature_patch"
  assert result["execution_strategy"] == "scoped_model_patch"
  assert "feature_patch_agent" in result["required_agents"]
  assert result["clarification_question"] == ""


def test_update_analysis_allows_concrete_existing_page_update():
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Update the onboarding page with a five-step conversational chat flow.",
      "candidate_files": ["src/components/OnboardingWizard.jsx"],
      "candidate_new_files": [],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/components/OnboardingWizard.jsx"],
    code_search_matches=[],
    user_prompt="update the onboarding page with a 5-step conversational chat flow",
  )

  assert result["update_mode"] == "feature_patch"
  assert result["execution_strategy"] == "scoped_model_patch"
  assert "feature_patch_agent" in result["required_agents"]


def test_update_analysis_does_not_require_new_file_agent_for_bug_fix():
  result = normalize_update_analysis(
    {
      "update_mode": "bug_fix",
      "request_kind": "bug_fix",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Fix broken save button.",
      "candidate_files": ["src/App.jsx"],
      "candidate_new_files": ["src/components/SaveButton.jsx"],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/App.jsx"],
    code_search_matches=[],
    user_prompt="Fix the save button not working",
  )

  assert result["candidate_new_files"] == []
  assert result["new_file_requirements"]["needed"] is False
  assert "new_file_requirement_agent" not in result["required_agents"]


def test_update_analysis_groups_contact_detail_list_into_scoped_tasks():
  prompt = """In lead(contact) module we want to provide the below things as page while click the initial contact

The Customer
Activity
Deals
Products
Projects
What's upcoming"""
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "large",
      "summary": "Add a contact detail page with customer, activity, deals, products, projects, and upcoming sections.",
      "feature_plan": {
        "name": "ContactDetailPage",
        "type": "page",
        "items": ["The Customer", "Activity", "Deals", "Products", "Projects", "What's upcoming"],
        "interaction": "Open when clicking the initial contact.",
      },
      "target_symbols": ["lead", "contact", "customer", "activity", "deals", "products", "projects", "upcoming"],
      "candidate_files": ["src/components/ModulesView.jsx", "src/data/mockData.js"],
      "candidate_new_files": [],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/components/ModulesView.jsx", "src/data/mockData.js"],
    code_search_matches=[],
    user_prompt=prompt,
  )

  assert result["candidate_new_files"] == [
    "src/pages/ContactDetailPage.jsx",
    "src/components/ContactDetailPage.jsx",
  ]
  assert len(result["scoped_update_tasks"]) == 4
  task_text = " ".join(task["prompt"] for task in result["scoped_update_tasks"]).lower()
  for expected in ["the customer", "activity", "deals", "products", "projects", "what's upcoming"]:
    assert expected in task_text
  assert result["scoped_update_tasks"][0]["candidate_new_files"] == [
    "src/pages/ContactDetailPage.jsx",
    "src/components/ContactDetailPage.jsx",
  ]
  assert result["scoped_update_tasks"][1]["candidate_new_files"] == []


def test_update_analysis_replaces_incomplete_model_tasks_for_list_request():
  prompt = """In lead(contact) module provide these pages when clicking a contact

The Customer
Activity
Deals
Products
Projects
What's upcoming"""
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "large",
      "summary": "Add contact detail pages.",
      "feature_plan": {
        "name": "ContactDetailPage",
        "type": "page",
        "items": ["The Customer", "Activity", "Deals", "Products", "Projects", "What's upcoming"],
        "interaction": "Open when clicking a contact.",
      },
      "target_symbols": ["lead", "contact"],
      "candidate_files": ["src/components/ModulesView.jsx", "src/data/mockData.js"],
      "candidate_new_files": [],
      "scoped_update_tasks": [
        {"id": "step_1", "summary": "Create contact detail shell", "prompt": "Create contact detail shell", "candidate_files": ["src/components/ModulesView.jsx"]},
        {"id": "step_2", "summary": "Add customer and activity", "prompt": "Add The Customer and Activity", "candidate_files": ["src/components/ModulesView.jsx", "src/data/mockData.js"]},
      ],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/components/ModulesView.jsx", "src/data/mockData.js"],
    code_search_matches=[],
    user_prompt=prompt,
  )

  task_text = " ".join(task["prompt"] for task in result["scoped_update_tasks"]).lower()
  for expected in ["the customer", "activity", "deals", "products", "projects", "what's upcoming"]:
    assert expected in task_text
  assert len(result["scoped_update_tasks"]) == 4


def test_scoped_update_runtime_allows_inferred_new_component_file():
  class NewComponentArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      assert "src/components/AIChatWidget.jsx" in prompt
      return {
        "status": "completed",
        "summary": "Added AI chat widget component.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": 'import React from "react";',
            "replace": 'import React from "react";\nimport AIChatWidget from "./components/AIChatWidget.jsx";',
            "expected_replacements": 1,
          },
          {
            "path": "src/App.jsx",
            "search": "return <main>Dashboard</main>;",
            "replace": "return <main>Dashboard<AIChatWidget /></main>;",
            "expected_replacements": 1,
          },
        ],
        "changed_files": [
          {
            "path": "src/components/AIChatWidget.jsx",
            "code": "export default function AIChatWidget() { return <aside>AI assistant ready</aside>; }\n",
          }
        ],
        "clarification_question": "",
      }

  artifact_provider = NewComponentArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": 'import React from "react";\nexport default function App() {\n  return <main>Dashboard</main>;\n}\n',
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "AIChatWidget" in by_path["src/App.jsx"]
      assert "AI assistant ready" in by_path["src/components/AIChatWidget.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Add AI chat widget to the dashboard",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert result["runtime"]["scoped_update"]["changed_file_paths"] == [
    "src/App.jsx",
    "src/components/AIChatWidget.jsx",
  ]
  assert written_files


def test_scoped_update_runtime_splits_broad_request_into_ordered_tasks():
  class MultiTaskArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      scoped_call = self.calls.count("scoped_update_artifact")
      if scoped_call == 1:
        assert "Scoped subtask 1 of 2" in prompt
        assert "Add AI chat widget" in prompt
        assert "src/components/AIChatWidget.jsx" in prompt
        return {
          "status": "completed",
          "summary": "Added AI chat widget component.",
          "edits": [
            {
              "path": "src/App.jsx",
              "search": 'import React from "react";',
              "replace": 'import React from "react";\nimport AIChatWidget from "./components/AIChatWidget.jsx";',
              "expected_replacements": 1,
            },
            {
              "path": "src/App.jsx",
              "search": "<main><h1>Dashboard</h1></main>",
              "replace": "<main><h1>Dashboard</h1><AIChatWidget /></main>",
              "expected_replacements": 1,
            },
          ],
          "changed_files": [
            {
              "path": "src/components/AIChatWidget.jsx",
              "code": "export default function AIChatWidget() { return <aside>AI assistant ready</aside>; }\n",
            }
          ],
          "clarification_question": "",
        }
      assert "Scoped subtask 2 of 2" in prompt
      assert "Previously applied subtasks" in prompt
      assert "Step 1 changed src/App.jsx, src/components/AIChatWidget.jsx" in prompt
      return {
        "status": "completed",
        "summary": "Updated dashboard title.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "<h1>Dashboard</h1>",
            "replace": "<h1>Aura CRM</h1>",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = MultiTaskArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": 'import React from "react";\nexport default function App() {\n  return <main><h1>Dashboard</h1></main>;\n}\n',
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "Aura CRM" in by_path["src/App.jsx"]
      assert "AIChatWidget" in by_path["src/App.jsx"]
      assert "AI assistant ready" in by_path["src/components/AIChatWidget.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Add AI chat widget to the dashboard and update the header title to Aura CRM",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 2
  assert result["runtime"]["scoped_update"]["task_count"] == 2
  assert len(result["runtime"]["scoped_update_task_results"]) == 2
  assert result["runtime"]["scoped_update_task_results"][0]["candidate_new_files"] == ["src/components/AIChatWidget.jsx"]
  assert result["runtime"]["scoped_update_task_results"][1]["candidate_new_files"] == []
  assert result["runtime"]["dynamic_agent_workflow"]["tasks"][0]["id"] == "step_1"
  assert result["runtime"]["dynamic_agent_workflow"]["tasks"][1]["dependencies"] == ["step_1"]
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == [
    "src/App.jsx",
    "src/components/AIChatWidget.jsx",
  ]
  assert written_files


def test_broad_feature_update_runs_dynamic_agents_before_scoped_patch():
  prompt = """In lead(contact) module provide these pages when clicking a contact

The Customer
Activity
Deals
Products
Projects
What's upcoming"""

  class AgenticUpdateControlProvider(FakeControlProvider):
    def __init__(self):
      self.trace_labels = []

    def generate_json(self, prompt_text, **kwargs):
      trace_label = kwargs.get("trace_label")
      self.trace_labels.append(trace_label)
      if trace_label == "update_analysis_agent":
        return {
          "update_mode": "feature_patch",
          "request_kind": "feature_patch",
          "execution_strategy": "scoped_model_patch",
          "scope": "large",
          "summary": "Add a clicked contact detail page with requested CRM sections.",
          "feature_plan": {
            "name": "ContactDetailPage",
            "type": "page",
            "items": ["The Customer", "Activity", "Deals", "Products", "Projects", "What's upcoming"],
            "interaction": "Open when clicking a contact in the lead module.",
          },
          "target_symbols": ["lead", "contact", "customer", "activity", "deals", "products", "projects", "upcoming"],
          "candidate_files": ["src/components/ModulesView.jsx", "src/data/mockData.js"],
          "candidate_new_files": [],
          "required_agents": ["feature_patch_agent"],
          "preserve_rules": ["Preserve unrelated modules and dashboard behavior."],
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "This is a broad bounded CRM feature update.",
        }
      return super().generate_json(prompt_text, **kwargs)

  class ContactDetailArtifactProvider(FakeArtifactProvider):
    def generate_json(self, prompt_text, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt_text, **kwargs)
      scoped_call = self.calls.count("scoped_update_artifact")
      if scoped_call == 1:
        assert "agentic_dynamic_context" in prompt_text
        return {
          "status": "completed",
          "summary": "Created contact detail shell.",
          "edits": [
            {
              "path": "src/components/ModulesView.jsx",
              "search": 'import React from "react";',
              "replace": 'import React from "react";\nimport ContactDetailPage from "./ContactDetailPage.jsx";',
              "expected_replacements": 1,
            },
            {
              "path": "src/components/ModulesView.jsx",
              "search": "<button>Initial Contact</button>",
              "replace": "<ContactDetailPage />",
              "expected_replacements": 1,
            },
          ],
          "changed_files": [
            {
              "path": "src/components/ContactDetailPage.jsx",
              "code": 'const tabs = ["Shell"];\nexport default function ContactDetailPage() { return <section>{tabs.join(", ")}</section>; }\n',
            }
          ],
          "clarification_question": "",
        }
      assert "src/components/ContactDetailPage.jsx" in prompt_text
      tab_sets = {
        2: 'const tabs = ["The Customer", "Activity"];',
        3: 'const tabs = ["The Customer", "Activity", "Deals", "Products"];',
        4: "const tabs = [\"The Customer\", \"Activity\", \"Deals\", \"Products\", \"Projects\", \"What's upcoming\"];",
      }
      previous = {
        2: 'const tabs = ["Shell"];',
        3: 'const tabs = ["The Customer", "Activity"];',
        4: 'const tabs = ["The Customer", "Activity", "Deals", "Products"];',
      }
      return {
        "status": "completed",
        "summary": "Added contact detail sections.",
        "edits": [
          {
            "path": "src/components/ContactDetailPage.jsx",
            "search": previous[scoped_call],
            "replace": tab_sets[scoped_call],
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = ContactDetailArtifactProvider()
  control_provider = AgenticUpdateControlProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Aura CRM</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport ModulesView from "./components/ModulesView.jsx";\ncreateRoot(document.getElementById("root")).render(<ModulesView />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/components/ModulesView.jsx", "content": 'import React from "react";\nexport default function ModulesView() { return <button>Initial Contact</button>; }\n'},
    {"path": "src/data/mockData.js", "content": "export const contacts = [{ id: 1, name: 'Acme' }];\n"},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "ContactDetailPage" in by_path["src/components/ModulesView.jsx"]
      assert "What's upcoming" in by_path["src/components/ContactDetailPage.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt=prompt,
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=control_provider,
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  action_history = result["runtime"]["action_history"]
  assert "RUN_PROMPT_ANALYST" not in action_history
  assert action_history.index("RUN_DYNAMIC_AGENT_PLANNER") < action_history.index("RUN_SCOPED_UPDATE_AGENT")
  assert action_history.index("RUN_DYNAMIC_SPECIALISTS") < action_history.index("RUN_SCOPED_UPDATE_AGENT")
  assert result["runtime"]["scoped_update"]["skipped_dynamic_agents"] is False
  assert result["runtime"]["dynamic_agent_workflow"]["active_agents"]
  assert result["runtime"]["dynamic_agent_workflow"]["planning_source"] == "scoped_update_registry_reuse"
  assert len(result["runtime"]["dynamic_agent_workflow"]["tasks"]) <= 4
  assert result["runtime"]["dynamic_specialist_results"]["status"] == "completed"
  assert result["runtime"]["dynamic_specialist_results"]["source"] == "scoped_update_registry_reuse"
  assert "prompt_analyst_agent" not in control_provider.trace_labels
  assert "domain_research_agent" not in control_provider.trace_labels
  assert "dynamic_task_decomposer" not in control_provider.trace_labels
  assert "dynamic_workflow_planner" not in control_provider.trace_labels
  assert not any(
    isinstance(label, str) and label.startswith("dynamic_agent_")
    for label in control_provider.trace_labels
  )
  assert artifact_provider.calls.count("scoped_update_artifact") == 4
  assert written_files


def test_scoped_feature_update_fills_created_component_when_later_subtask_no_patches():
  prompt = """In lead(contact) module provide these pages when clicking a contact

The Customer
Activity
Deals
Products
Projects
What's upcoming"""

  class ControlProvider(FakeControlProvider):
    def generate_json(self, prompt_text, **kwargs):
      if kwargs.get("trace_label") == "update_analysis_agent":
        return {
          "update_mode": "feature_patch",
          "request_kind": "feature_patch",
          "execution_strategy": "scoped_model_patch",
          "scope": "large",
          "summary": "Add a clicked contact detail page with requested sections.",
          "feature_plan": {
            "name": "ContactDetailPage",
            "type": "page",
            "items": ["The Customer", "Activity", "Deals", "Products", "Projects", "What's upcoming"],
            "interaction": "Open when clicking a contact.",
          },
          "target_symbols": ["lead", "contact", "customer", "activity", "deals", "products", "projects", "upcoming"],
          "candidate_files": ["src/components/ModulesView.jsx", "src/data/mockData.js"],
          "candidate_new_files": [],
          "preserve_rules": ["Preserve unrelated modules."],
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "Bounded feature patch.",
        }
      return super().generate_json(prompt_text, **kwargs)

  class ArtifactProvider(FakeArtifactProvider):
    def generate_json(self, prompt_text, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt_text, **kwargs)
      if self.calls.count("scoped_update_artifact") == 1:
        return {
          "status": "completed",
          "summary": "Created contact detail shell.",
          "edits": [
            {
              "path": "src/components/ModulesView.jsx",
              "search": 'import React from "react";',
              "replace": 'import React from "react";\nimport ContactDetailPage from "./ContactDetailPage.jsx";',
              "expected_replacements": 1,
            },
            {
              "path": "src/components/ModulesView.jsx",
              "search": "<button>Initial Contact</button>",
              "replace": "<ContactDetailPage />",
              "expected_replacements": 1,
            },
          ],
          "changed_files": [
            {
              "path": "src/components/ContactDetailPage.jsx",
              "code": "export default function ContactDetailPage() { return <section>Shell</section>; }\n",
            }
          ],
          "clarification_question": "",
        }
      return {
        "status": "blocked",
        "summary": "Gemini returned no scoped edits or changed files for the approved files.",
        "edits": [],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = ArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Aura CRM</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport ModulesView from "./components/ModulesView.jsx";\ncreateRoot(document.getElementById("root")).render(<ModulesView />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/components/ModulesView.jsx", "content": 'import React from "react";\nexport default function ModulesView() { return <button>Initial Contact</button>; }\n'},
    {"path": "src/data/mockData.js", "content": "export const contacts = [{ id: 1, name: 'Acme' }];\n"},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "ContactDetailPage" in by_path["src/components/ModulesView.jsx"]
      assert "The Customer" in by_path["src/components/ContactDetailPage.jsx"]
      assert "What's upcoming" in by_path["src/components/ContactDetailPage.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt=prompt,
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=ControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 3
  assert result["runtime"]["scoped_update_task_results"][1]["changed_file_paths"] == ["src/components/ContactDetailPage.jsx"]
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == [
    "src/components/ModulesView.jsx",
    "src/components/ContactDetailPage.jsx",
  ]
  assert written_files


def test_scoped_feature_update_rejects_unapproved_new_component_file():
  with pytest.raises(ScopedUpdateGuardError, match="unapproved file"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "changed_files": [
          {
            "path": "src/components/AIChatWidget.jsx",
            "code": "export default function AIChatWidget() { return <aside />; }\n",
          }
        ],
        "edits": [],
        "clarification_question": "",
      },
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": ["src/components/OtherWidget.jsx"],
      },
      existing_files=[{"path": "src/App.jsx", "content": "export default function App() { return null; }"}],
    )


def test_scoped_update_rejects_candidate_new_file_that_already_exists():
  with pytest.raises(ScopedUpdateGuardError, match="unapproved file"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "changed_files": [
          {
            "path": "src/Existing.jsx",
            "code": "export default function Existing() { return <main>Updated</main>; }\n",
          }
        ],
        "edits": [],
        "clarification_question": "",
      },
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": ["src/Existing.jsx"],
      },
      existing_files=[
        {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
        {"path": "src/Existing.jsx", "content": "export default function Existing() { return <main>Existing</main>; }"},
      ],
    )


def test_scoped_feature_update_rejects_empty_new_file_content():
  with pytest.raises(ScopedUpdateGuardError, match="empty or invalid code"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "changed_files": [{"path": "src/components/AIChatWidget.jsx", "code": "   "}],
        "edits": [],
        "clarification_question": "",
      },
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": ["src/components/AIChatWidget.jsx"],
      },
      existing_files=[{"path": "src/App.jsx", "content": "export default function App() { return null; }"}],
    )


def test_scoped_update_applies_exact_edits_without_returning_complete_file():
  existing = "export default function ModuleShowcase() {\n  return <nav>Top modules</nav>;\n}\n"

  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "edits": [
        {
          "path": "src/components/ModuleShowcase.jsx",
          "search": "<nav>Top modules</nav>",
          "replace": '<aside aria-label="Modules">Left modules</aside>',
          "expected_replacements": 1,
        }
      ],
      "changed_files": [],
    },
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/ModuleShowcase.jsx"]},
    existing_files=[{"path": "src/components/ModuleShowcase.jsx", "content": existing}],
  )

  assert changed == [
    {
      "path": "src/components/ModuleShowcase.jsx",
      "content": (
        'import React from "react";\n'
        "export default function ModuleShowcase() {\n"
        '  return <aside aria-label="Modules">Left modules</aside>;\n'
        "}\n"
      ),
    }
  ]


def test_scoped_update_applies_unique_normalized_edit_match():
  existing = (
    "export default function AnalyticsView() {\n"
    "  const dateRanges = [\n"
    "    'Last 30 Days',\n"
    "  ];\n"
    "  return dateRanges.join(', ');\n"
    "}\n"
  )

  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "edits": [
        {
          "path": "src/components/AnalyticsView.jsx",
          "search": "const dateRanges = [\n'Last 30 Days',\n];",
          "replace": "const dateRanges = [\n'Last 7 Days',\n'Last 30 Days',\n'Last 90 Days',\n'All Time',\n];",
          "expected_replacements": 1,
        }
      ],
      "changed_files": [],
    },
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/AnalyticsView.jsx"]},
    existing_files=[{"path": "src/components/AnalyticsView.jsx", "content": existing}],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/AnalyticsView.jsx"
  assert "'Last 7 Days'" in changed[0]["content"]
  assert "'All Time'" in changed[0]["content"]
  assert "  const dateRanges = [" in changed[0]["content"]


def test_scoped_update_applies_unique_fuzzy_line_window_edit_match():
  existing = (
    "export default function AnalyticsView() {\n"
    "  const rangeOptions = [\n"
    "    { label: 'Last 7 Days', value: '7d' },\n"
    "    { label: 'Last 30 Days', value: '30d' },\n"
    "    { label: 'Last 90 Days', value: '90d' },\n"
    "  ];\n"
    "  const activeRange = rangeOptions.find((option) => option.value === selectedRange);\n"
    "  return <button>{activeRange?.label}</button>;\n"
    "}\n"
  )

  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "edits": [
        {
          "path": "src/components/AnalyticsView.jsx",
          "search": (
            "const rangeOptions = [\n"
            "  { label: 'Last 7 days', value: '7d' },\n"
            "  { label: 'Last 30 Days', value: '30d' },\n"
            "  { label: 'Last 90 Days', value: '90d' },\n"
            "];\n"
            "const activeRange = rangeOptions.find((range) => range.value === selectedRange);"
          ),
          "replace": (
            "const rangeOptions = [\n"
            "  { label: 'Last 7 Days', value: '7d' },\n"
            "  { label: 'Last 30 Days', value: '30d' },\n"
            "  { label: 'Last 90 Days', value: '90d' },\n"
            "  { label: 'All Time', value: 'all' },\n"
            "];\n"
            "const activeRange = rangeOptions.find((option) => option.value === selectedRange);"
          ),
          "expected_replacements": 1,
        }
      ],
      "changed_files": [],
    },
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/AnalyticsView.jsx"]},
    existing_files=[{"path": "src/components/AnalyticsView.jsx", "content": existing}],
  )

  assert len(changed) == 1
  assert "{ label: 'All Time', value: 'all' }" in changed[0]["content"]
  assert "return <button>{activeRange?.label}</button>;" in changed[0]["content"]


def test_scoped_update_blocks_ambiguous_fuzzy_line_window_edit_match():
  repeated_block = (
    "  const rangeOptions = [\n"
    "    { label: 'Last 7 Days', value: '7d' },\n"
    "    { label: 'Last 30 Days', value: '30d' },\n"
    "    { label: 'Last 90 Days', value: '90d' },\n"
    "  ];\n"
    "  const activeRange = rangeOptions.find((option) => option.value === selectedRange);\n"
  )
  existing = (
    "export default function AnalyticsView() {\n"
    f"{repeated_block}"
    "  const dashboard = activeRange;\n"
    f"{repeated_block}"
    "  return <button>{dashboard?.label}</button>;\n"
    "}\n"
  )

  with pytest.raises(ScopedUpdateGuardError, match="could not apply the edit safely"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "edits": [
          {
            "path": "src/components/AnalyticsView.jsx",
            "search": (
              "const rangeOptions = [\n"
              "  { label: 'Last 7 days', value: '7d' },\n"
              "  { label: 'Last 30 Days', value: '30d' },\n"
              "  { label: 'Last 90 Days', value: '90d' },\n"
              "];\n"
              "const activeRange = rangeOptions.find((range) => range.value === selectedRange);"
            ),
            "replace": "const rangeOptions = [];\nconst activeRange = null;",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
      },
      update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/AnalyticsView.jsx"]},
      existing_files=[{"path": "src/components/AnalyticsView.jsx", "content": existing}],
    )


def test_scoped_update_blocks_ambiguous_normalized_edit_match():
  existing = (
    "export default function AnalyticsView() {\n"
    "  const dateRanges = [\n"
    "    'Last 30 Days',\n"
    "  ];\n"
    "  const backupRanges = [\n"
    "    'Last 30 Days',\n"
    "  ];\n"
    "  return dateRanges.join(', ');\n"
    "}\n"
  )

  with pytest.raises(ScopedUpdateGuardError, match="could not apply the edit safely"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "edits": [
          {
            "path": "src/components/AnalyticsView.jsx",
            "search": "'Last 30 Days',",
            "replace": "'Last 7 Days',",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
      },
      update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/AnalyticsView.jsx"]},
      existing_files=[{"path": "src/components/AnalyticsView.jsx", "content": existing}],
    )


def test_scoped_update_agent_requests_structured_schema_and_bounded_output_budget():
  captured = {}

  class Provider:
    def generate_json(self, prompt, **kwargs):
      captured["prompt"] = prompt
      captured.update(kwargs)
      return {
        "status": "completed",
        "summary": "Moved modules.",
        "edits": [],
        "changed_files": [{"path": "src/App.jsx", "code": RAW_APP_CODE}],
        "preserved": [],
        "self_checks": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Move modules to a left sidebar",
    update_analysis={"candidate_files": ["src/App.jsx"]},
    existing_files=[{"path": "src/App.jsx", "content": RAW_APP_CODE}],
    code_search_matches=[],
  )

  assert result["status"] == "completed"
  assert captured["response_schema"]["properties"]["edits"]["type"] == "ARRAY"
  assert captured["response_schema"]["properties"]["edits"]["items"]["properties"]["search_replace"]["type"] == "STRING"
  assert "needs_scope_expansion" in captured["response_schema"]["properties"]["status"]["enum"]
  assert captured["response_schema"]["properties"]["requested_files"]["type"] == "ARRAY"
  assert captured["max_output_tokens"] == SCOPED_UPDATE_MAX_OUTPUT_TOKENS
  assert "SEARCH/REPLACE" in captured["system_instruction"]
  assert "scoped_edit_plan" in captured["prompt"]
  assert "python_scoped_code_localizer" in captured["prompt"]
  assert "src/App.jsx" in captured["prompt"]


def test_scoped_update_normalizes_files_wrapper_response():
  changed = validate_scoped_update_changes(
    {
      "summary": "Updated analytics filter.",
      "files": [
        {
          "path": "src/components/AnalyticsView.jsx",
          "content": "export default function AnalyticsView() {\n  return <button>Last 7 Days</button>;\n}\n",
        }
      ],
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/AnalyticsView.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/AnalyticsView.jsx",
        "content": "export default function AnalyticsView() {\n  return <button>Last 30 Days</button>;\n}\n",
      }
    ],
  )

  assert changed == [
    {
      "path": "src/components/AnalyticsView.jsx",
      "content": (
        'import React from "react";\n'
        "export default function AnalyticsView() {\n"
        "  return <button>Last 7 Days</button>;\n"
        "}\n"
      ),
    }
  ]


def test_scoped_update_normalizes_nested_alias_edit_response():
  changed = validate_scoped_update_changes(
    {
      "result": {
        "state": "completed",
        "message": "Updated the bell label.",
        "changes": [
          {
            "file_path": "src/components/Dashboard.jsx",
            "old_snippet": "<button>Bell</button>",
            "new_snippet": '<button aria-label="Notifications">Notifications</button>',
            "expected_matches": 1,
          }
        ],
      }
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/Dashboard.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard() {\n  return <button>Bell</button>;\n}\n",
      }
    ],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/Dashboard.jsx"
  assert 'aria-label="Notifications"' in changed[0]["content"]


def test_scoped_update_normalizes_search_replace_block_edit_response():
  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "summary": "Updated the bell label.",
      "edits": [
        {
          "path": "src/components/Dashboard.jsx",
          "search_replace": (
            "<<<<<<< SEARCH\n"
            "<button>Bell</button>\n"
            "=======\n"
            '<button aria-label="Notifications">Notifications</button>\n'
            ">>>>>>> REPLACE"
          ),
          "expected_replacements": 1,
        }
      ],
      "changed_files": [],
      "clarification_question": "",
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/Dashboard.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard() {\n  return <button>Bell</button>;\n}\n",
      }
    ],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/Dashboard.jsx"
  assert 'aria-label="Notifications"' in changed[0]["content"]


def test_scoped_update_normalizes_raw_search_replace_block_text_response():
  changed = validate_scoped_update_changes(
    (
      "File: src/components/Dashboard.jsx\n"
      "<<<<<<< SEARCH\n"
      "<button>Bell</button>\n"
      "=======\n"
      '<button aria-label="Notifications">Notifications</button>\n'
      ">>>>>>> REPLACE"
    ),
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/Dashboard.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard() {\n  return <button>Bell</button>;\n}\n",
      }
    ],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/Dashboard.jsx"
  assert 'aria-label="Notifications"' in changed[0]["content"]


def test_scoped_update_normalizes_top_level_path_search_replace_block_response():
  changed = validate_scoped_update_changes(
    {
      "status": "completed",
      "summary": "Updated the bell label.",
      "path": "src/components/Dashboard.jsx",
      "search_replace": (
        "<<<<<<< SEARCH\n"
        "<button>Bell</button>\n"
        "=======\n"
        '<button aria-label="Notifications">Notifications</button>\n'
        ">>>>>>> REPLACE"
      ),
      "changed_files": [],
      "clarification_question": "",
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/Dashboard.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard() {\n  return <button>Bell</button>;\n}\n",
      }
    ],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/Dashboard.jsx"
  assert 'aria-label="Notifications"' in changed[0]["content"]


def test_scoped_update_normalizes_nested_alias_changed_files_response():
  changed = validate_scoped_update_changes(
    {
      "output": {
        "status": "completed",
        "summary": "Updated analytics view.",
        "file_changes": [
          {
            "filename": "src/components/AnalyticsView.jsx",
            "updated_code": "export default function AnalyticsView() {\n  return <section>AI assistant ready</section>;\n}\n",
          }
        ],
      }
    },
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/components/AnalyticsView.jsx"],
    },
    existing_files=[
      {
        "path": "src/components/AnalyticsView.jsx",
        "content": "export default function AnalyticsView() {\n  return <section>Old analytics</section>;\n}\n",
      }
    ],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/components/AnalyticsView.jsx"
  assert "AI assistant ready" in changed[0]["content"]


def test_scoped_update_agent_retries_once_after_empty_patch_response():
  calls = []
  output_budgets = []

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      output_budgets.append(kwargs.get("max_output_tokens"))
      if len(calls) == 1:
        return {
          "status": "completed",
          "summary": "Updated dashboard.",
          "edits": [],
          "changed_files": [],
          "clarification_question": "",
        }
      return {
        "status": "completed",
        "summary": "Updated dashboard.",
        "edits": [
          {
            "path": "src/components/Dashboard.jsx",
            "search": "<button>Bell</button>",
            "replace": '<button aria-label="Notifications">Notifications</button>',
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Update the bell icon click behavior",
    update_analysis={"candidate_files": ["src/components/Dashboard.jsx"]},
    existing_files=[
      {
        "path": "src/components/Dashboard.jsx",
        "content": "export default function Dashboard() {\n  return <button>Bell</button>;\n}\n",
      }
    ],
    code_search_matches=[],
  )

  assert len(calls) == 2
  assert "returned no usable edits or changed_files" in calls[1]
  assert "Allowed existing files with complete current contents" in calls[1]
  assert "Focused raw source excerpts" not in calls[1]
  assert output_budgets[1] == SCOPED_UPDATE_EMPTY_PATCH_RETRY_MAX_OUTPUT_TOKENS
  assert result["edits"][0]["replace"] == '<button aria-label="Notifications">Notifications</button>'


def test_deterministic_existing_list_content_update_changes_appends_tigers():
  from backend.llm.agent_runtime.scoped_update import deterministic_existing_list_content_update_changes

  existing = (
    "import React from 'react';\n\n"
    "export default function AnimalsPage() {\n"
    "  const animals = [\n"
    '    { id: 1, name: "Lion", description: "King of the jungle" },\n'
    "  ];\n"
    "  return (\n"
    "    <section>\n"
    "      {animals.map((animal) => (\n"
    '        <article key={animal.id}>{animal.name}</article>\n'
    "      ))}\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )
  changed = deterministic_existing_list_content_update_changes(
    prompt="Add 5 different tigers to the animals page",
    update_analysis={
      "update_mode": "targeted_patch",
      "candidate_files": ["src/pages/AnimalsPage.jsx"],
    },
    existing_files=[{"path": "src/pages/AnimalsPage.jsx", "content": existing}],
  )

  assert len(changed) == 1
  assert changed[0]["path"] == "src/pages/AnimalsPage.jsx"
  assert "Bengal Tiger" in changed[0]["content"]
  assert "Siberian Tiger" in changed[0]["content"]
  assert "Malayan Tiger" in changed[0]["content"]
  assert changed[0]["content"].count('name: "') >= 6


def test_deterministic_existing_list_content_update_handles_singular_tiger_request():
  from backend.llm.agent_runtime.scoped_update import deterministic_existing_list_content_update_changes

  existing = (
    "export const animals = [\n"
    '  { id: 1, name: "Lion", description: "King of the jungle" },\n'
    "];\n"
  )
  changed = deterministic_existing_list_content_update_changes(
    prompt="add the tiger in our website as animal",
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/data/animals.js"],
      "feature_plan": {"items": ["5 tiger entries"]},
    },
    existing_files=[{"path": "src/data/animals.js", "content": existing}],
  )

  assert len(changed) == 1
  assert "Bengal Tiger" in changed[0]["content"]
  assert "5 tiger entries" not in changed[0]["content"]


def test_scoped_update_sequence_recovers_after_no_effective_file_changes():
  from backend.llm.agent_runtime.scoped_update.runtime import run_scoped_update_sequence

  existing = (
    "export default function AnimalsPage() {\n"
    "  const animals = [\n"
    '    { id: 1, name: "Lion", description: "King of the jungle" },\n'
    "  ];\n"
    "  return <section>{animals.length}</section>;\n"
    "}\n"
  )

  class Provider:
    def generate_json(self, prompt, **kwargs):
      return {
        "status": "completed",
        "summary": "Updated animals page.",
        "edits": [],
        "changed_files": [
          {
            "path": "src/pages/AnimalsPage.jsx",
            "code": existing,
          }
        ],
        "clarification_question": "",
      }

  scoped_result, changed_files, _task_results = run_scoped_update_sequence(
    Provider(),
    prompt="Add 5 different tigers to the animals page",
    update_analysis={
      "update_mode": "targeted_patch",
      "candidate_files": ["src/pages/AnimalsPage.jsx"],
      "scoped_update_tasks": [],
    },
    existing_files=[{"path": "src/pages/AnimalsPage.jsx", "content": existing}],
    code_search_matches=[],
  )

  assert scoped_result["deterministic_fallback"] == "existing_list_content"
  assert len(changed_files) == 1
  assert "Bengal Tiger" in changed_files[0]["content"]


def test_scoped_update_normalizes_legacy_permission_question_as_scope_expansion():
  from backend.llm.agent_runtime.scoped_update import normalize_scoped_update_response

  result = normalize_scoped_update_response(
    {
      "status": "needs_clarification",
      "summary": "Need permission for the data file.",
      "edits": [],
      "changed_files": [],
      "clarification_question": (
        "The current plan does not allow modifications to `src/data/animals.js`. "
        "I need explicit permission to modify this file."
      ),
    }
  )

  assert result["status"] == "needs_scope_expansion"
  assert result["requested_files"] == ["src/data/animals.js"]


def test_scoped_update_normalizes_scope_expansion_wording_as_internal_request():
  from backend.llm.agent_runtime.scoped_update import normalize_scoped_update_response

  result = normalize_scoped_update_response(
    {
      "status": "needs_clarification",
      "summary": "Need the animal data file.",
      "edits": [],
      "changed_files": [],
      "clarification_question": (
        "Adding the tiger data to `src/data/animals.js` would require scope expansion "
        "to include that file."
      ),
    }
  )

  assert result["status"] == "needs_scope_expansion"
  assert result["requested_files"] == ["src/data/animals.js"]


def test_update_analysis_discards_historical_enhancement_tasks():
  contaminated_prompt = (
    "add the tiger in our website as animal\n\n"
    "Additional conversation context for model routing and planning. "
    "Use it only if the current user request refers to or depends on it; otherwise ignore it.\n\n"
    "Previous enhancement-plan context available to the Chief Orchestrator:\n"
    "Assistant response:\nProject Overview**\nKey Pages & Sections**\n"
    "Current Strengths**\nGaps & Areas for Improvement**\nConcise Enhancement Plan**"
  )
  result = normalize_update_analysis(
    {
      "update_mode": "feature_patch",
      "request_kind": "feature_patch",
      "execution_strategy": "scoped_model_patch",
      "scope": "small",
      "summary": "Add tiger animal data.",
      "feature_plan": {
        "name": "AnimalDataExtension",
        "type": "page",
        "items": ["5 tiger entries"],
        "interaction": "Display tigers on the animals page.",
      },
      "candidate_files": ["src/data/animals.js", "src/pages/Animals.jsx"],
      "candidate_new_files": ["src/utils/AnimalDataExtension.css"],
      "scoped_update_tasks": [
        {
          "id": "step_1",
          "prompt": "add the tiger in our website as animal and Project Overview",
          "candidate_files": ["src/data/animals.js"],
        },
        {
          "id": "step_2",
          "prompt": "Add sections for Current Strengths and Gaps & Areas for Improvement",
          "candidate_files": ["src/pages/Animals.jsx"],
        },
      ],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/data/animals.js", "src/pages/Animals.jsx"],
    code_search_matches=[],
    user_prompt=contaminated_prompt,
  )

  assert result["candidate_new_files"] == []
  assert result["new_file_requirements"]["needed"] is False
  assert result["scoped_update_tasks"] == []


def test_scoped_update_agent_strips_historical_orchestrator_context():
  captured = {}

  class Provider:
    def generate_json(self, prompt, **kwargs):
      captured["prompt"] = prompt
      return {
        "status": "completed",
        "summary": "Added tiger data.",
        "edits": [
          {
            "path": "src/data/animals.js",
            "search": "export const animals = [];",
            "replace": 'export const animals = [{ id: 1, name: "Bengal Tiger" }];',
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "requested_files": [],
        "clarification_question": "",
      }

  run_scoped_update_agent(
    Provider(),
    prompt=(
      "add the tiger in our website as animal\n\n"
      "Additional conversation context for model routing and planning.\n\n"
      "Previous enhancement-plan context available to the Chief Orchestrator:\n"
      "Project Overview**\nCurrent Strengths**"
    ),
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/data/animals.js"]},
    existing_files=[{"path": "src/data/animals.js", "content": "export const animals = [];"}],
    code_search_matches=[],
  )

  assert "add the tiger in our website as animal" in captured["prompt"]
  assert "Project Overview" not in captured["prompt"]
  assert "Current Strengths" not in captured["prompt"]


def test_scoped_update_keeps_genuine_user_ambiguity_as_clarification():
  from backend.llm.agent_runtime.scoped_update import normalize_scoped_update_response

  result = normalize_scoped_update_response(
    {
      "status": "needs_clarification",
      "summary": "The requested destination is ambiguous.",
      "edits": [],
      "changed_files": [],
      "clarification_question": "Which catalog page should receive the new pagination controls?",
    }
  )

  assert result["status"] == "needs_clarification"
  assert result["requested_files"] == []


def test_scoped_update_auto_expands_omitted_safe_existing_file():
  from backend.llm.agent_runtime.scoped_update.runtime import run_scoped_update_sequence

  calls = []
  expansion_events = []
  data_content = 'export const animals = [{ id: 1, name: "Lion" }];\n'

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      if len(calls) == 1:
        return {
          "status": "needs_scope_expansion",
          "summary": "The animal records are stored in the data module.",
          "edits": [],
          "changed_files": [],
          "requested_files": ["src/data/animals.js"],
          "clarification_question": "",
        }
      assert "src/data/animals.js" in prompt
      assert data_content.strip() in prompt
      return {
        "status": "completed",
        "summary": "Added a tiger record.",
        "edits": [
          {
            "path": "src/data/animals.js",
            "search": data_content.strip(),
            "replace": 'export const animals = [{ id: 1, name: "Lion" }, { id: 2, name: "Tiger" }];',
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "requested_files": [],
        "clarification_question": "",
      }

  result, changed_files, _task_results = run_scoped_update_sequence(
    Provider(),
    prompt="Add a tiger to the animals page.",
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/pages/Animals.jsx"],
      "candidate_new_files": [],
      "scoped_update_tasks": [],
    },
    existing_files=[
      {
        "path": "src/pages/Animals.jsx",
        "content": 'import { animals } from "../data/animals.js";\nexport default function Animals() { return animals.length; }\n',
      },
      {"path": "src/data/animals.js", "content": data_content},
    ],
    code_search_matches=[
      {"path": "src/data/animals.js", "matched_terms": ["animals"], "snippets": [data_content]},
    ],
    scope_expansion_callback=expansion_events.append,
  )

  assert len(calls) == 2
  assert changed_files[0]["path"] == "src/data/animals.js"
  assert 'name: "Tiger"' in changed_files[0]["content"]
  assert result["scope_expansions"][0]["newly_approved_paths"] == ["src/data/animals.js"]
  assert expansion_events[0]["task_id"] == "scoped_update"


def test_scoped_update_legacy_permission_expands_scope_and_preserves_later_task_changes():
  from backend.llm.agent_runtime.scoped_update.runtime import run_scoped_update_sequence

  data_content = (
    "export const animals = [\n"
    '  { id: 1, name: "Lion", description: "King of the jungle" },\n'
    "];\n"
  )
  page_content = (
    'import { animals } from "../data/animals.js";\n'
    "export default function Animals() {\n"
    "  return <section>{animals.map((animal) => <article key={animal.id}>{animal.name}</article>)}</section>;\n"
    "}\n"
  )

  class Provider:
    def __init__(self):
      self.calls = 0

    def generate_json(self, prompt, **kwargs):
      self.calls += 1
      if self.calls == 1:
        return {
          "status": "needs_clarification",
          "summary": "Need the animal data file.",
          "edits": [],
          "changed_files": [],
          "clarification_question": (
            "The current plan does not allow modifications to `src/data/animals.js`. "
            "To add the 5 tiger entries, I need explicit permission to modify this file."
          ),
        }
      if self.calls in {2, 3}:
        assert "src/data/animals.js" in prompt
        return {
          "status": "completed",
          "summary": "Updated animal data.",
          "edits": [],
          "changed_files": [{"path": "src/data/animals.js", "code": data_content}],
          "requested_files": [],
          "clarification_question": "",
        }
      assert "Previously applied subtasks" in prompt
      return {
        "status": "completed",
        "summary": "Added the tiger category heading.",
        "edits": [
          {
            "path": "src/pages/Animals.jsx",
            "search": "  return <section>{animals.map",
            "replace": '  return <section><h2>Tiger collection</h2>{animals.map',
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "requested_files": [],
        "clarification_question": "",
      }

  provider = Provider()
  result, changed_files, task_results = run_scoped_update_sequence(
    provider,
    prompt="Add 5 different tigers to the animals page and add a tiger collection heading.",
    update_analysis={
      "update_mode": "feature_patch",
      "candidate_files": ["src/pages/Animals.jsx", "src/data/animals.js"],
      "candidate_new_files": [],
      "scoped_update_tasks": [
        {
          "id": "add_tiger_data",
          "summary": "Add five tiger records.",
          "prompt": "Add 5 different tigers to the animal data.",
          "candidate_files": ["src/pages/Animals.jsx"],
          "candidate_new_files": [],
        },
        {
          "id": "update_animals_page",
          "summary": "Add a tiger collection heading.",
          "prompt": "Add a tiger collection heading to the animals page.",
          "candidate_files": ["src/pages/Animals.jsx"],
          "candidate_new_files": [],
        },
      ],
    },
    existing_files=[
      {"path": "src/pages/Animals.jsx", "content": page_content},
      {"path": "src/data/animals.js", "content": data_content},
    ],
    code_search_matches=[
      {"path": "src/pages/Animals.jsx", "matched_terms": ["animals"], "snippets": [page_content]},
      {"path": "src/data/animals.js", "matched_terms": ["animals"], "snippets": [data_content]},
    ],
  )

  by_path = {item["path"]: item["content"] for item in changed_files}
  assert provider.calls == 4
  assert "Bengal Tiger" in by_path["src/data/animals.js"]
  assert "Malayan Tiger" in by_path["src/data/animals.js"]
  assert "Tiger collection" in by_path["src/pages/Animals.jsx"]
  assert task_results[0]["scope_expansions"][0]["accepted_paths"] == ["src/data/animals.js"]
  assert result["scope_expansions"][0]["task_id"] == "add_tiger_data"


@pytest.mark.parametrize(
  ("requested_path", "content", "error_match"),
  [
    ("src/missing.js", None, "missing project file"),
    ("../secrets.txt", "SECRET=value", "unsafe scope-expansion path"),
    ("backend/.env", "SECRET=value", "environment secret files"),
    ("src/dist/generated.js", "export const generated = true;", "generated, cached, or vendor"),
    ("src/assets/logo.png", "data:image/png;base64,AAAA", "binary or encoded asset"),
    ("src/huge.js", "x" * 160001, "too large"),
  ],
)
def test_scoped_update_scope_expansion_rejects_unsafe_files(requested_path, content, error_match):
  from backend.llm.agent_runtime.scoped_update.runtime import resolve_scoped_update_scope_expansion

  existing_files = [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]
  if content is not None:
    existing_files.append({"path": requested_path, "content": content})

  with pytest.raises(ScopedUpdateGuardError, match=error_match):
    resolve_scoped_update_scope_expansion(
      {
        "status": "needs_scope_expansion",
        "requested_files": [requested_path],
        "_candidate_paths": ["src/App.jsx"],
      },
      update_analysis={"candidate_files": ["src/App.jsx"]},
      existing_files=existing_files,
      retry_count=1,
    )


def test_scoped_update_scope_expansion_rejects_excessive_files():
  from backend.llm.agent_runtime.scoped_update.runtime import resolve_scoped_update_scope_expansion

  requested_paths = [f"src/data/items{index}.js" for index in range(4)]
  with pytest.raises(ScopedUpdateGuardError, match="four-existing-file safety limit"):
    resolve_scoped_update_scope_expansion(
      {
        "status": "needs_scope_expansion",
        "requested_files": requested_paths,
        "_candidate_paths": ["src/App.jsx"],
      },
      update_analysis={"candidate_files": ["src/App.jsx"]},
      existing_files=[
        {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
        *[
          {"path": path, "content": "export const items = [];\n"}
          for path in requested_paths
        ],
      ],
      retry_count=1,
    )


def test_scoped_update_scope_expansion_stops_after_two_attempts():
  from backend.llm.agent_runtime.scoped_update.runtime import run_scoped_update_sequence

  requested_paths = ["src/data/first.js", "src/data/second.js", "src/data/third.js"]

  class Provider:
    def __init__(self):
      self.calls = 0

    def generate_json(self, prompt, **kwargs):
      path = requested_paths[self.calls]
      self.calls += 1
      return {
        "status": "needs_scope_expansion",
        "summary": f"Need {path}.",
        "edits": [],
        "changed_files": [],
        "requested_files": [path],
        "clarification_question": "",
      }

  provider = Provider()
  with pytest.raises(ScopedUpdateGuardError, match="two-attempt internal scope-expansion limit"):
    run_scoped_update_sequence(
      provider,
      prompt="Update the data pipeline.",
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": [],
        "scoped_update_tasks": [],
      },
      existing_files=[
        {"path": "src/App.jsx", "content": "export default function App() { return null; }"},
        *[
          {"path": path, "content": "export const items = [];\n"}
          for path in requested_paths
        ],
      ],
      code_search_matches=[],
    )

  assert provider.calls == 3


def test_scoped_update_empty_retry_preserves_complete_file_context():
  calls = []
  huge_unrelated_block = "const unrelatedMetric = 42;\n" * 500
  existing = (
    "import React from 'react';\n"
    f"{huge_unrelated_block}"
    "export default function ModulesView() {\n"
    "  const contactTabs = ['Customer'];\n"
    "  return <section>{contactTabs.join(', ')}</section>;\n"
    "}\n"
    f"{huge_unrelated_block}"
  )

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      if len(calls) == 1:
        return {
          "status": "blocked",
          "summary": "Gemini returned no scoped edits or changed files for the approved files.",
          "edits": [],
          "changed_files": [],
          "clarification_question": "",
        }
      assert "Allowed existing files with complete current contents" in prompt
      assert "Focused raw source excerpts" not in prompt
      assert "contactTabs" in prompt
      assert "returned no usable edits or changed_files" in prompt
      assert prompt.count("unrelatedMetric") >= calls[0].count("unrelatedMetric")
      return {
        "status": "completed",
        "summary": "Added activity contact tab.",
        "edits": [
          {
            "path": "src/components/ModulesView.jsx",
            "search": "const contactTabs = ['Customer'];",
            "replace": "const contactTabs = ['Customer', 'Activity'];",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Make contacts open a customer activity tab in ModulesView",
    update_analysis={"candidate_files": ["src/components/ModulesView.jsx"]},
    existing_files=[{"path": "src/components/ModulesView.jsx", "content": existing}],
    code_search_matches=[
      {
        "path": "src/components/ModulesView.jsx",
        "matched_terms": ["contacts", "activity", "ModulesView"],
        "snippets": ["  const contactTabs = ['Customer'];\n  return <section>{contactTabs.join(', ')}</section>;"],
      }
    ],
  )
  changed = validate_scoped_update_changes(
    result,
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/ModulesView.jsx"]},
    existing_files=[{"path": "src/components/ModulesView.jsx", "content": existing}],
  )

  assert len(calls) == 2
  assert "Allowed existing files with complete current contents" in calls[0]
  assert "Focused raw source excerpts" not in calls[0]
  assert changed[0]["path"] == "src/components/ModulesView.jsx"
  assert "['Customer', 'Activity']" in changed[0]["content"]


def test_scoped_update_retries_top_of_file_clarification_with_setup_context():
  calls = []
  unrelated_block = "const unrelatedMetric = 42;\n" * 520
  existing = (
    'import React, { useState } from "react";\n'
    'import "./styles.css";\n'
    "\n"
    "export default function App() {\n"
    "  const [expandedModule, setExpandedModule] = useState(null);\n"
    '  const [activeTab, setActiveTab] = useState("home");\n'
    f"{unrelated_block}"
    "  return (\n"
    "    <div>\n"
    "      <footer>\n"
    "        <button>Support us</button>\n"
    "      </footer>\n"
    "    </div>\n"
    "  );\n"
    "}\n"
  )

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      if len(calls) == 1:
        assert "Allowed existing files with complete current contents" in prompt
        assert "Focused raw source excerpts" not in prompt
        assert "import React, { useState } from" in prompt
        assert "const [expandedModule, setExpandedModule]" in prompt
        assert "<button>Support us</button>" in prompt
        return {
          "status": "needs_clarification",
          "summary": "Need file setup.",
          "edits": [],
          "changed_files": [],
          "clarification_question": (
            "I need the top of src/App.jsx to add the import for SupportModal and the state variables "
            "(supportModalOpen, supportTopic) required to wire the footer links. The current excerpts "
            "only show the footer. Could you provide the top of the file?"
          ),
        }
      assert "returned no usable edits or changed_files" in prompt
      assert "const [expandedModule, setExpandedModule]" in prompt
      return {
        "status": "completed",
        "summary": "Wired support footer action.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "<button>Support us</button>",
            "replace": "<button onClick={() => setExpandedModule('support')}>Support us</button>",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="same like support us buttons also not working",
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/App.jsx"]},
    existing_files=[{"path": "src/App.jsx", "content": existing}],
    code_search_matches=[
      {
        "path": "src/App.jsx",
        "matched_terms": ["support", "footer"],
        "snippets": ["      <footer>\n        <button>Support us</button>\n      </footer>"],
      }
    ],
  )
  changed = validate_scoped_update_changes(
    result,
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/App.jsx"]},
    existing_files=[{"path": "src/App.jsx", "content": existing}],
  )

  assert len(calls) == 2
  assert changed[0]["path"] == "src/App.jsx"
  assert "setExpandedModule('support')" in changed[0]["content"]


def test_scoped_update_large_file_uses_full_prompt_on_first_call():
  calls = []
  existing = (
    "import React from 'react';\n"
    + ("const unrelatedMetric = 42;\n" * 1800)
    + "export default function ModulesView() {\n"
    + "  const contactTabs = ['Customer'];\n"
    + "  return <section>{contactTabs.join(', ')}</section>;\n"
    + "}\n"
  )

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      assert "Allowed existing files with complete current contents" in prompt
      assert "Focused raw source excerpts" not in prompt
      assert "Make the smallest complete code change" in prompt
      assert "Previous scoped update problem" not in prompt
      assert "contactTabs" in prompt
      assert prompt.count("unrelatedMetric") > 1000
      return {
        "status": "completed",
        "summary": "Added activity contact tab.",
        "edits": [
          {
            "path": "src/components/ModulesView.jsx",
            "search": "const contactTabs = ['Customer'];",
            "replace": "const contactTabs = ['Customer', 'Activity'];",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Make contacts open a customer activity tab in ModulesView",
    update_analysis={"candidate_files": ["src/components/ModulesView.jsx"]},
    existing_files=[{"path": "src/components/ModulesView.jsx", "content": existing}],
    code_search_matches=[
      {
        "path": "src/components/ModulesView.jsx",
        "matched_terms": ["contacts", "activity", "ModulesView"],
        "snippets": ["  const contactTabs = ['Customer'];\n  return <section>{contactTabs.join(', ')}</section>;"],
      }
    ],
  )

  assert len(calls) == 1
  assert result["edits"][0]["replace"] == "const contactTabs = ['Customer', 'Activity'];"


def test_scoped_update_medium_feature_patch_uses_full_prompt_on_first_call():
  calls = []
  unrelated_block = "const unrelatedMetric = 42;\n" * 420
  existing = (
    "import React from 'react';\n"
    f"{unrelated_block}"
    "export default function ModulesView() {\n"
    "  const contactTabs = ['Customer'];\n"
    "  return <section>{contactTabs.join(', ')}</section>;\n"
    "}\n"
    f"{unrelated_block}"
  )

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      assert "Focused raw source excerpts" not in prompt
      assert "Allowed existing files with complete current contents" in prompt
      assert "contactTabs" in prompt
      assert prompt.count("unrelatedMetric") >= 800
      return {
        "status": "completed",
        "summary": "Added activity contact tab.",
        "edits": [
          {
            "path": "src/components/ModulesView.jsx",
            "search": "const contactTabs = ['Customer'];",
            "replace": "const contactTabs = ['Customer', 'Activity'];",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Make contacts open a customer activity tab in ModulesView",
    update_analysis={"update_mode": "feature_patch", "candidate_files": ["src/components/ModulesView.jsx"]},
    existing_files=[{"path": "src/components/ModulesView.jsx", "content": existing}],
    code_search_matches=[
      {
        "path": "src/components/ModulesView.jsx",
        "matched_terms": ["contacts", "activity", "ModulesView"],
        "snippets": ["  const contactTabs = ['Customer'];\n  return <section>{contactTabs.join(', ')}</section>;"],
      }
    ],
  )

  assert len(calls) == 1
  assert result["edits"][0]["replace"] == "const contactTabs = ['Customer', 'Activity'];"


def test_scoped_update_empty_blocked_response_has_clear_reason():
  with pytest.raises(ScopedUpdateGuardError, match="no scoped edits or changed files"):
    validate_scoped_update_changes(
      {
        "status": "blocked",
        "summary": "",
        "edits": [],
        "changed_files": [],
        "clarification_question": "",
      },
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/components/Dashboard.jsx"],
      },
      existing_files=[
        {
          "path": "src/components/Dashboard.jsx",
          "content": "export default function Dashboard() { return null; }\n",
        }
      ],
    )


def test_scoped_update_agent_retries_once_after_invalid_json():
  calls = []

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      if len(calls) == 1:
        raise RuntimeError("Gemini returned invalid JSON: {")
      return {
        "status": "completed",
        "summary": "Updated button label.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "Save",
            "replace": "Save changes",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  result = run_scoped_update_agent(
    Provider(),
    prompt="Change Save button to Save changes",
    update_analysis={"candidate_files": ["src/App.jsx"]},
    existing_files=[{"path": "src/App.jsx", "content": "export default function App() { return <button>Save</button>; }"}],
    code_search_matches=[],
  )

  assert len(calls) == 2
  assert "previous scoped update response was rejected" in calls[1]
  assert result["status"] == "completed"
  assert result["edits"][0]["replace"] == "Save changes"


def test_scoped_update_agent_converts_repeated_invalid_json_to_guard_error():
  calls = []

  class Provider:
    def generate_json(self, prompt, **kwargs):
      calls.append(prompt)
      raise RuntimeError("Gemini returned invalid JSON: {")

  with pytest.raises(ScopedUpdateGuardError, match="invalid scoped patch JSON"):
    run_scoped_update_agent(
      Provider(),
      prompt="Change Save button to Save changes",
      update_analysis={"candidate_files": ["src/App.jsx"]},
      existing_files=[{"path": "src/App.jsx", "content": "export default function App() { return <button>Save</button>; }"}],
      code_search_matches=[],
    )

  assert len(calls) == 2
  assert "previous scoped update response was rejected" in calls[1]


def test_scoped_update_runtime_repairs_after_repeated_invalid_json_response():
  class InvalidJsonThenValidPatchArtifactProvider(FakeArtifactProvider):
    def __init__(self):
      super().__init__()
      self.prompts = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      self.prompts.append(prompt)
      if kwargs.get("trace_label") != "scoped_update_artifact":
        return super().generate_json(prompt, **kwargs)
      scoped_calls = self.calls.count("scoped_update_artifact")
      if scoped_calls <= 2:
        raise RuntimeError("Gemini returned invalid JSON: {")
      return {
        "status": "completed",
        "summary": "Updated button label.",
        "edits": [
          {
            "path": "src/App.jsx",
            "search": "Save",
            "replace": "Save changes",
            "expected_replacements": 1,
          }
        ],
        "changed_files": [],
        "clarification_question": "",
      }

  artifact_provider = InvalidJsonThenValidPatchArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Dashboard</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": "export default function App() { return <button>Save</button>; }\n"},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "Save changes" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Change Save button to Save changes",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls.count("scoped_update_artifact") == 3
  assert "previous scoped patch failed" in artifact_provider.prompts[2].lower()
  assert result["runtime"]["repair_attempts"] == 1
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/App.jsx"]
  assert written_files


def test_scoped_bug_fix_rejects_large_component_rewrite():
  existing = "export default function App() {\n  return <main>Existing store</main>;\n}\n"
  replacement = "export default function App() {\n  return <main>" + ("Completely different website " * 20) + "</main>;\n}\n"

  with pytest.raises(ScopedUpdateGuardError, match="rewrite too much"):
    validate_scoped_update_changes(
      {
        "status": "completed",
        "changed_files": [{"path": "src/App.jsx", "code": replacement}],
      },
      update_analysis={"update_mode": "bug_fix", "candidate_files": ["src/App.jsx"]},
      existing_files=[{"path": "src/App.jsx", "content": existing}],
    )


def test_generation_prompt_requires_route_backed_pages_for_multi_module_sites():
  prompt = build_website_prompt(
    "Generate an AI CRM with contacts, deals, campaigns, inbox, and finance modules",
    artifact_mode="website_generation",
  )

  assert "src/pages/*" in prompt
  assert "React Router" in prompt
  assert "do not implement the entire product as hash-anchor sections on one long page" in prompt
  assert "Never generate a monolithic src/App.jsx" in prompt
  assert "src/theme/tokens.js" in prompt
  assert "If the user provides brand guidelines" in prompt
  assert "dynamically infer the token system" in prompt
  assert "static default theme" in prompt
  assert "component_manifest" in prompt
  assert "EnterpriseComplianceFooter" in prompt
  assert "PAS or AIDA" in prompt
  assert "loading, error, hover" in prompt
  assert "aria-labels" in prompt
  assert "JSON-LD" in prompt


def test_full_regeneration_requires_explicit_model_approval():
  base_response = {
    "update_mode": "full_regeneration",
    "request_kind": "full_regeneration",
    "execution_strategy": "full_dynamic_workflow",
    "scope": "large",
    "summary": "Rebuild the website.",
    "candidate_files": [],
    "allow_full_regeneration": False,
  }

  blocked = normalize_update_analysis(base_response, existing_paths=["src/App.jsx"], code_search_matches=[])
  approved = normalize_update_analysis(
    base_response | {"allow_full_regeneration": True},
    existing_paths=["src/App.jsx"],
    code_search_matches=[],
  )

  assert blocked["update_mode"] == "needs_clarification"
  assert blocked["execution_strategy"] == "clarify"
  assert approved["update_mode"] == "full_regeneration"
  assert approved["execution_strategy"] == "full_dynamic_workflow"


def test_targeted_patch_requires_model_supplied_patch_intent():
  result = normalize_update_analysis(
    {
      "update_mode": "targeted_patch",
      "request_kind": "brand_name_update",
      "execution_strategy": "deterministic_patch",
      "scope": "small",
      "summary": "Rename the website.",
      "candidate_files": ["src/App.jsx"],
      "allow_full_regeneration": False,
    },
    existing_paths=["src/App.jsx"],
    code_search_matches=[],
  )

  assert result["update_mode"] == "targeted_patch"
  assert result["execution_strategy"] == "scoped_model_patch"
  assert result["targeted_patch"]["kind"] == "brand_name_update"
  assert result["targeted_patch"]["new_value"] == ""


def test_simple_theme_update_uses_targeted_patch_without_dynamic_generation():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  written_files = []
  existing_files = [
    {
      "path": "package.json",
      "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest","lucide-react":"latest"},"devDependencies":{"tailwindcss":"^3.4.17","postcss":"^8.5.0","autoprefixer":"^10.4.20"}}',
    },
    {"path": "index.html", "content": "<!doctype html><title>Veloce</title><div id=\"root\"></div><script type=\"module\" src=\"/src/main.jsx\"></script>"},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\nimport "./index.css";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {
      "path": "src/index.css",
      "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\nbody { margin: 0; }",
    },
    {
      "path": "src/App.jsx",
      "content": 'import React from "react";\nexport default function App() { return <main className="min-h-screen bg-gray-50"><section className="bg-gradient-to-r from-indigo-600 to-purple-500"><button className="bg-indigo-600 hover:bg-indigo-700 text-white">Shop the Collection</button></section></main>; }',
    },
    {
      "path": "src/data/products.js",
      "content": 'export const products = [{ name: "Everyday Carry Tote", price: "$48" }];',
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      paths = [file_item["path"] for file_item in arguments["generated_website"]["files"]]
      assert "src/data/products.js" in paths
      return {"status": "valid", "file_count": len(paths), "paths": paths}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "from-red-600" in by_path["src/App.jsx"]
      assert "to-yellow-400" in by_path["src/App.jsx"]
      assert "bg-yellow-50" in by_path["src/App.jsx"]
      assert "--vibe-theme-primary: #dc2626" in by_path["src/index.css"]
      assert by_path["src/data/products.js"] == existing_files[-1]["content"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="change the website background color to red and yellow",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert "RUN_DYNAMIC_AGENT_PLANNER" not in result["runtime"]["action_history"]
  assert "RUN_CODE_AGENT" not in result["runtime"]["action_history"]
  assert result["runtime"]["dynamic_agent_workflow"]["planning_source"] == "model_selected_targeted_patch"
  assert result["runtime"]["final_output"]["changed_file_paths"] == ["src/index.css", "src/App.jsx"]
  assert_written_files_match_preview(written_files, preview_files)


def test_simple_website_name_update_patches_brand_locations_without_regeneration():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  written_files = []
  existing_files = [
    {
      "path": "package.json",
      "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}',
    },
    {"path": "index.html", "content": '<!doctype html><html><head><title>MeadowBrook Farms</title><meta name="application-name" content="MeadowBrook Farms"></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": 'import React from "react";\nimport { Header } from "./components/Header.jsx";\nexport default function App() { return <><Header /><main><h1>Sustainably Grown</h1></main></>; }'},
    {"path": "src/components/Header.jsx", "content": 'export function Header() { return <header><a className="brand-logo" aria-label="MeadowBrook home">MeadowBrook</a><nav>Seasonal Produce</nav></header>; }'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      paths = [file_item["path"] for file_item in arguments["generated_website"]["files"]]
      assert "src/components/Header.jsx" in paths
      return {"status": "valid", "file_count": len(paths), "paths": paths}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "<title>worktual</title>" in by_path["index.html"]
      assert 'content="worktual"' in by_path["index.html"]
      assert ">worktual</a>" in by_path["src/components/Header.jsx"]
      assert 'aria-label="worktual home"' in by_path["src/components/Header.jsx"]
      assert by_path["src/App.jsx"] == existing_files[4]["content"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="change the website name to worktual",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert "RUN_DYNAMIC_AGENT_PLANNER" not in result["runtime"]["action_history"]
  assert "RUN_CODE_AGENT" not in result["runtime"]["action_history"]
  assert result["runtime"]["targeted_update"]["kind"] == "brand_name_update"
  assert result["runtime"]["final_output"]["changed_file_paths"] == ["index.html", "src/components/Header.jsx"]
  assert_written_files_match_preview(written_files, preview_files)


def test_targeted_update_uses_model_patch_intent_not_prompt_regex():
  class ModelDirectedBrandControlProvider(FakeControlProvider):
    def generate_json(self, prompt, **kwargs):
      if kwargs.get("trace_label") == "update_analysis_agent":
        return {
          "update_mode": "targeted_patch",
          "request_kind": "brand_name_update",
          "execution_strategy": "deterministic_patch",
          "scope": "small",
          "summary": "Apply the approved brand replacement.",
          "target_symbols": ["brand logo"],
          "candidate_files": ["index.html", "src/App.jsx"],
          "required_agents": ["targeted_update_agent"],
          "targeted_patch": {
            "kind": "brand_name_update",
            "old_value": "Northstar",
            "new_value": "Acme Studio",
            "target_description": "Replace the existing visible brand text.",
          },
          "preserve_rules": ["Do not change layout or product data."],
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "The model identified the concrete brand replacement from context.",
        }
      return super().generate_json(prompt, **kwargs)

  artifact_provider = FakeArtifactProvider()
  preview_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Northstar</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": 'export default function App() { return <header><strong>Northstar</strong></header>; }'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "<title>Acme Studio</title>" in by_path["index.html"]
      assert "<strong>Acme Studio</strong>" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="please apply the approved existing brand correction",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=ModelDirectedBrandControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert result["runtime"]["update_analysis"]["targeted_patch"]["new_value"] == "Acme Studio"
  assert result["runtime"]["targeted_update"]["changed_file_paths"] == ["index.html", "src/App.jsx"]
  assert preview_files


def test_brand_update_infers_visible_react_brand_locations_without_old_value():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  existing_files = [
    {
      "path": "package.json",
      "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}',
    },
    {"path": "index.html", "content": '<title>Worktual &amp; Co</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": 'import React from "react";\nexport default function App() { return <><header><a className="text-2xl font-bold">worktual &amp; co</a></header><main><h1>Elevate Your Workspace</h1></main><footer>{new Date().getFullYear()} worktual &amp; co All rights reserved.</footer></>; }',
    },
    {"path": "src/data/products.js", "content": 'export const products = [{ name: "Worktual & Co Tote" }];'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"]), "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "<title>Yoga &amp; Choga</title>" in by_path["index.html"]
      assert ">Yoga &amp; Choga</a>" in by_path["src/App.jsx"]
      assert "Yoga &amp; Choga All rights reserved." in by_path["src/App.jsx"]
      assert by_path["src/data/products.js"] == existing_files[-1]["content"]
      assert "Elevate Your Workspace" in by_path["src/App.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="change the website name to Yoga & Choga",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert "RUN_DYNAMIC_AGENT_PLANNER" not in result["runtime"]["action_history"]
  assert "RUN_CODE_AGENT" not in result["runtime"]["action_history"]
  assert result["runtime"]["targeted_update"]["changed_file_paths"] == ["index.html", "src/App.jsx"]
  assert preview_files


def test_rebrand_from_old_to_new_replaces_exact_brand_without_touching_product_data():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>MeadowBrook Farms</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": 'export default function App() { return <main><h1>MeadowBrook Farms</h1><p>Visit MeadowBrook Farms today.</p></main>; }'},
    {"path": "src/data/products.js", "content": 'export const products = [{ name: "MeadowBrook Farms Harvest Box" }];'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"]), "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "<title>Worktual</title>" in by_path["index.html"]
      assert "<h1>Worktual</h1>" in by_path["src/App.jsx"]
      assert "Visit Worktual today." in by_path["src/App.jsx"]
      assert by_path["src/data/products.js"] == existing_files[-1]["content"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="rebrand from MeadowBrook Farms to Worktual",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert result["runtime"]["final_output"]["changed_file_paths"] == ["index.html", "src/App.jsx"]
  assert preview_files


def test_simple_name_update_no_match_blocks_full_regeneration():
  artifact_provider = FakeArtifactProvider()
  calls = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "src/App.jsx", "content": 'export default function App() { return <main><h1>Welcome</h1></main>; }'},
  ]

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool after no-match guard: {name}")

  with pytest.raises(AgentRuntimeLoopError, match="Targeted update could not be applied safely"):
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="change the website name to Worktual",
      routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert artifact_provider.calls == []
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_vague_followup_update_asks_for_clarification_without_dynamic_regeneration():
  artifact_provider = FakeArtifactProvider()
  calls = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Yoga &amp; Choga</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {"path": "src/App.jsx", "content": 'export default function App() { return <main><h1>Yoga &amp; Choga</h1></main>; }'},
  ]

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    raise AssertionError(f"Unexpected tool after ambiguous-update guard: {name}")

  with pytest.raises(AgentRuntimeLoopError, match="Update request needs clarification"):
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="change the main files also not only index.html",
      routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "model selected update"},
      control_provider=FakeControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
    )

  assert artifact_provider.calls == []
  assert calls == ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def test_generic_page_update_uses_model_selected_scoped_patch():
  artifact_provider = FakeArtifactProvider()
  calls = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/components/OnboardingWizard.jsx", "content": "export default function OnboardingWizard() { return <section>Onboarding</section>; }"},
    {"path": "src/App.jsx", "content": 'import OnboardingWizard from "./components/OnboardingWizard.jsx";\nexport default function App() { return <OnboardingWizard />; }'},
  ]

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="update the onboarding page",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "model selected update"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["scoped_update_artifact"]
  assert result["runtime"]["update_analysis"]["update_mode"] == "feature_patch"
  assert result["runtime"]["action_history"][:4] == scoped_update_action_prefix()


def test_onboarding_chat_update_uses_deterministic_scoped_patch_without_model_call():
  class OnboardingChatControlProvider(FakeControlProvider):
    def generate_json(self, prompt, **kwargs):
      if kwargs.get("trace_label") == "update_analysis_agent":
        return {
          "update_mode": "feature_patch",
          "request_kind": "feature_patch",
          "execution_strategy": "scoped_model_patch",
          "scope": "small",
          "summary": "Replace the traditional 3-step onboarding form with a 5-step conversational AI chat interface.",
          "target_symbols": ["OnboardingWizard", "onboarding", "chat", "five steps"],
          "candidate_files": ["src/components/OnboardingWizard.jsx"],
          "candidate_new_files": [],
          "required_agents": ["feature_patch_agent"],
          "preserve_rules": ["Preserve unrelated files."],
          "allow_full_regeneration": False,
          "clarification_question": "",
          "reason": "The request is a bounded onboarding component update.",
        }
      return super().generate_json(prompt, **kwargs)

  class NoModelPatchArtifactProvider:
    name = "no-model-patch-artifact"
    provider_role = ARTIFACT_PROVIDER_ROLE
    calls = []

    def generate_json(self, prompt, **kwargs):
      self.calls.append(kwargs.get("trace_label"))
      raise AssertionError("Onboarding chat deterministic scoped patch should not call artifact model.")

  artifact_provider = NoModelPatchArtifactProvider()
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/App.jsx", "content": 'import OnboardingWizard from "./components/OnboardingWizard.jsx";\nexport default function App() { return <OnboardingWizard onComplete={() => {}} />; }'},
    {
      "path": "src/components/OnboardingWizard.jsx",
      "content": 'export default function OnboardingWizard({ onComplete }) { return <form><h1>Traditional onboarding</h1><button type="button" onClick={() => onComplete({})}>Finish</button></form>; }',
    },
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      by_path = {item["path"]: item["code"] for item in arguments["generated_website"]["files"]}
      assert "onboardingSteps" in by_path["src/components/OnboardingWizard.jsx"]
      assert "Conversational onboarding chat" in by_path["src/components/OnboardingWizard.jsx"]
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"])}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      by_path = {item["path"]: item["content"] for item in arguments["files"]}
      assert "onboardingSteps" in by_path["src/components/OnboardingWizard.jsx"]
      assert "Complete setup" in by_path["src/components/OnboardingWizard.jsx"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="update the onboarding process with 5 steps and those things done in chat only ai chat",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "model selected update"},
    control_provider=OnboardingChatControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert result["runtime"]["scoped_update"]["changed_file_paths"] == ["src/components/OnboardingWizard.jsx"]
  assert written_files


def test_pagination_page_size_update_patches_existing_constant_without_regeneration():
  artifact_provider = FakeArtifactProvider()
  preview_files = []
  written_files = []
  existing_files = [
    {"path": "package.json", "content": '{"scripts":{"build":"vite"},"dependencies":{"@vitejs/plugin-react":"latest","vite":"latest","react":"latest","react-dom":"latest"}}'},
    {"path": "index.html", "content": '<title>Shop</title><div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
    {"path": "src/main.jsx", "content": 'import React from "react";\nimport { createRoot } from "react-dom/client";\nimport App from "./App.jsx";\ncreateRoot(document.getElementById("root")).render(<App />);'},
    {"path": "src/index.css", "content": "body { margin: 0; }"},
    {
      "path": "src/App.jsx",
      "content": 'import React, { useMemo, useState } from "react";\nconst ITEMS_PER_PAGE = 20;\nexport default function App() { const [currentPage] = useState(1); const products = Array.from({ length: 50 }); const paginatedProducts = useMemo(() => products.slice((currentPage - 1) * ITEMS_PER_PAGE, currentPage * ITEMS_PER_PAGE), [currentPage]); return <main>{paginatedProducts.length}</main>; }',
    },
    {"path": "src/data/products.js", "content": 'export const products = [{ name: "Tote" }];'},
  ]

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": existing_files, "file_count": len(existing_files)}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"]), "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_files.append(arguments["files"])
      by_path = {file_item["path"]: file_item["content"] for file_item in arguments["files"]}
      assert "const ITEMS_PER_PAGE = 25;" in by_path["src/App.jsx"]
      assert by_path["src/data/products.js"] == existing_files[-1]["content"]
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed", "mode": "backend_preview_integrity"}
    if name == "WRITE_PROJECT_FILES":
      written_files.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted", "key": arguments.get("key")}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="increase the each page size to 25",
    routing_result={"intent": "website_update", "next_action": "update_website", "next_tool": "analyze_update_request", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == []
  assert "RUN_DYNAMIC_AGENT_PLANNER" not in result["runtime"]["action_history"]
  assert "RUN_CODE_AGENT" not in result["runtime"]["action_history"]
  assert result["runtime"]["targeted_update"]["kind"] == "pagination_page_size_update"
  assert result["runtime"]["execution_mode"] == "model_selected_targeted_patch_loop"
  assert result["runtime"]["final_output"]["changed_file_paths"] == ["src/App.jsx"]
  assert_written_files_match_preview(written_files, preview_files)


def test_real_agent_runtime_repairs_after_failed_preview_build():
  artifact_provider = FakeArtifactProvider()
  build_statuses = ["failed", "ready"]
  progress_events = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      status = build_statuses.pop(0)
      failed_build_log = (
        "Building staged candidate files before project commit.\n\n"
        "vite v7.3.5 building client environment for production...\n"
        "transforming...\n"
        "src/App.jsx:12:7: ERROR: Unexpected token"
      )
      return {
        "project_id": arguments["project_id"],
        "version": {
          "status": status,
          "build_log": failed_build_log if status == "failed" else "built",
          "preview_url": "/api/previews/project-1/v2/" if status == "ready" else None,
        },
        "staged": True,
      }
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
    emit_progress=lambda step, message, **kwargs: progress_events.append({"step": step, "message": message, **kwargs}),
  )

  assert artifact_provider.calls == ["generate_website_artifact", "repair_website_artifact"]
  assert any(step["agent"] == "Repair Agent" for step in result["runtime"]["steps"])
  assert result["runtime"]["final_output"]["preview_status"] == "ready"
  repair_progress = next(event for event in progress_events if event["step"] == "agent.loop.run_repair_agent")
  assert "Unexpected token" in repair_progress["message"]
  assert "Unexpected token" in repair_progress["detail"]["repair_reason"]
  assert "vite v7.3.5 building" not in repair_progress["detail"]["repair_reason"]


def test_real_agent_runtime_skips_gemini_repair_when_runtime_budget_is_low(monkeypatch):
  monkeypatch.setenv("REPAIR_RUNTIME_MIN_REMAINING_SECONDS", "120")
  artifact_provider = FakeArtifactProvider()
  build_statuses = ["failed"]
  calls = []

  def tool_executor(name, context, user, arguments):
    calls.append(name)
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": len(arguments["generated_website"]["files"]), "paths": [file_item["path"] for file_item in arguments["generated_website"]["files"]]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      status = build_statuses.pop(0)
      return {
        "project_id": arguments["project_id"],
        "version": {
          "status": status,
          "build_log": "src/App.jsx:12:7: ERROR: Unexpected token" if status == "failed" else "built",
          "preview_url": "/api/previews/project-1/v2/" if status == "ready" else None,
        },
        "staged": True,
      }
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    raise AssertionError(f"Unexpected tool: {name}")

  with pytest.raises(AgentRuntimeLoopError) as exc_info:
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate a CRM website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=artifact_provider,
      prepared_sections={},
      tool_executor=tool_executor,
      timeout_seconds=60,
    )

  assert artifact_provider.calls == ["generate_website_artifact"]
  assert "Skipped Gemini repair because less than" in str(exc_info.value)
  assert_incremental_write_before_preview_calls(calls)
  assert "VALIDATE_PROJECT_ARTIFACT" in calls
  assert "BUILD_STAGED_PROJECT_PREVIEW" in calls


def test_real_agent_runtime_repairs_after_staged_preview_tool_exception():
  artifact_provider = FakeArtifactProvider()
  preview_calls = 0
  writes = []

  def tool_executor(name, context, user, arguments):
    nonlocal preview_calls
    if name == "READ_PROJECT_FILES":
      return {"project_id": arguments["project_id"], "files": [], "file_count": 0}
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      preview_calls += 1
      if preview_calls == 1:
        raise RuntimeError("Vite process crashed")
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "build_log": "built"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "passed"}
    if name == "WRITE_PROJECT_FILES":
      writes.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": 1, "local_sync": None}
    if name == "PERSIST_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "status": "persisted"}
    raise AssertionError(f"Unexpected tool: {name}")

  result = execute_real_agent_runtime_loop(
    project_id="project-1",
    user=FakeUser(),
    tool_context=ToolRuntimeContext(store=None, settings=None),
    prompt="Generate a CRM website",
    routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
    control_provider=FakeControlProvider(),
    artifact_provider=artifact_provider,
    prepared_sections={},
    tool_executor=tool_executor,
  )

  assert artifact_provider.calls == ["generate_website_artifact", "repair_website_artifact"]
  assert preview_calls == 2
  assert writes
  assert any(file_item["path"] == "src/App.jsx" for file_item in writes[-1])
  failed_preview_calls = [
    call for call in result["runtime"]["tool_calls"] if call.get("name") == "BUILD_STAGED_PROJECT_PREVIEW" and call.get("status") == "failed"
  ]
  assert failed_preview_calls
  assert result["runtime"]["final_output"]["preview_status"] == "ready"


def test_real_agent_runtime_restores_previous_files_after_final_preview_failure():
  writes = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {
        "project_id": arguments["project_id"],
        "files": [{"path": "src/App.jsx", "content": "export default function App() { return <main>old</main>; }"}],
        "file_count": 1,
      }
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "failed", "build_log": "Syntax error"}, "staged": True}
    if name == "WRITE_PROJECT_FILES":
      writes.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    raise AssertionError(f"Unexpected tool: {name}")

  with pytest.raises(AgentRuntimeLoopError, match="restored previous project files"):
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate a CRM website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=FakeArtifactProvider(),
      prepared_sections={},
      tool_executor=tool_executor,
      max_repair_attempts=0,
    )

  assert writes[-1] == [
    {
      "path": "src/App.jsx",
      "content": "export default function App() { return <main>old</main>; }",
    }
  ]


def test_real_agent_runtime_does_not_empty_write_when_initial_read_fails():
  writes = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      raise RuntimeError("database read failed")
    if name == "WRITE_PROJECT_FILES":
      writes.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    raise AssertionError(f"Unexpected tool: {name}")

  with pytest.raises(AgentRuntimeLoopError, match="no successful READ_PROJECT_FILES snapshot"):
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate a CRM website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=FakeArtifactProvider(),
      prepared_sections={},
      tool_executor=tool_executor,
      max_repair_attempts=0,
    )

  assert writes == []


def test_real_agent_runtime_does_not_commit_when_visual_qa_is_skipped():
  writes = []

  def tool_executor(name, context, user, arguments):
    if name == "READ_PROJECT_FILES":
      return {
        "project_id": arguments["project_id"],
        "files": [{"path": "src/App.jsx", "content": "export default function App() { return <main>old</main>; }"}],
        "file_count": 1,
      }
    if name == "LOAD_PROJECT_MEMORY":
      return {"project_id": arguments["project_id"], "memories": [], "memory_count": 0}
    if name == "VALIDATE_PROJECT_ARTIFACT":
      return {"status": "valid", "file_count": 1, "paths": ["src/App.jsx"]}
    if name == "BUILD_STAGED_PROJECT_PREVIEW":
      return {"project_id": arguments["project_id"], "version": {"status": "ready", "build_log": "built", "preview_url": "/api/previews/project-1/v1/"}, "staged": True}
    if name == "RUN_PREVIEW_VISUAL_QA":
      return {"project_id": arguments["project_id"], "status": "skipped", "warnings": ["No browser command found."]}
    if name == "WRITE_PROJECT_FILES":
      writes.append(arguments["files"])
      return {"project_id": arguments["project_id"], "file_count": len(arguments["files"]), "local_sync": None}
    raise AssertionError(f"Unexpected tool: {name}")

  with pytest.raises(AgentRuntimeLoopError, match="restored previous project files"):
    execute_real_agent_runtime_loop(
      project_id="project-1",
      user=FakeUser(),
      tool_context=ToolRuntimeContext(store=None, settings=None),
      prompt="Generate a CRM website",
      routing_result={"intent": "website_generation", "next_action": "generate_website", "next_tool": "analyze_prompt", "reason": "ready"},
      control_provider=FakeControlProvider(),
      artifact_provider=FakeArtifactProvider(),
      prepared_sections={},
      tool_executor=tool_executor,
      max_repair_attempts=0,
    )

  assert writes[-1] == [
    {
      "path": "src/App.jsx",
      "content": "export default function App() { return <main>old</main>; }",
    }
  ]
