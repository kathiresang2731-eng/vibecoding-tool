from __future__ import annotations

from backend.agents.gemini_client.client import (
  build_generate_json_payload,
  build_generation_config,
  execution_stage_for_trace,
  model_role_for_trace,
  thinking_level_for_trace,
)
from backend.agents.request_complexity import ADAPTIVE_ROUTE_LARGE_PROJECT, classify_adaptive_request_route
from backend.agents.orchestration.routing import deterministic_routing_result
from backend.agents.prompting.builders import build_routing_prompt
from backend.agents.requirement_confirmation.routing import confirmed_routing_result
from backend.agents.streaming.task_planner import resolve_scoped_target_paths
from backend.agents.streaming.parallel_file_workers import _assign_worker_step_budgets
from backend.api.generation_stream import call_generation_pipeline_with_current_telemetry
from backend.api.admin_users import create_admin_user_payload
from backend.api.models import AdminCreateUserRequest, AdminUpdateUserRequest, GenerateRequest, ResumeGenerationRequest
from backend.api.generation import default_credit_reservation_for_route, resolve_control_model_for_request, resolve_credit_reservation_estimate
from backend.storage import UserContext
from backend.storage.token_pricing import estimate_model_usage_cost
from fastapi import HTTPException
import pytest


def test_routing_prompt_is_compact_but_keeps_core_contract_examples() -> None:
  prompt = build_routing_prompt("write a code for reverse number in python")

  assert len(prompt) < 4000
  assert '"write a code for reverse number in python" => simple_code' in prompt
  assert '"give me the information about this website" => project_info' in prompt
  assert "Use website_update only" in prompt


def test_deterministic_intent_fast_path_is_disabled() -> None:
  simple = deterministic_routing_result("provide a python program for neon number")
  env = deterministic_routing_result("create .env file for this project")
  crm = deterministic_routing_result("Generate the website for CRM with auth, onboarding, dashboard, leads, deals, sales, projects, products and main AI chat")

  assert simple is None
  assert env is None
  assert crm is None


def test_crm_requirement_routes_as_large_generation_without_model_call() -> None:
  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) After auth provide the onboarding process
  3) once onboarding done provide the dashboard with 4 types report and analytics
  4) provide modules: leads & contact, deals, sales, project, product, main ai chat
  brand guidelines primary black secondary purple others white and grey shadow
  """

  route = classify_adaptive_request_route(prompt, intent="website_generation")

  assert route.route == ADAPTIVE_ROUTE_LARGE_PROJECT
  assert route.use_parallel_workers is True


def test_named_missing_file_does_not_fall_back_to_unrelated_content_matches() -> None:
  paths = ["src/App.jsx", "src/pages/Dashboard.jsx"]
  files_map = {
    "src/App.jsx": "export default function App(){ return <Dashboard /> }",
    "src/pages/Dashboard.jsx": "export default function Dashboard(){ return <main>Fix profile</main> }",
  }

  assert resolve_scoped_target_paths("fix MissingProfile.jsx", paths=paths, files_map=files_map) == []


def test_secret_env_target_resolves_to_example_file_when_available() -> None:
  paths = [".env.example", "src/App.jsx"]
  files_map = {".env.example": "API_KEY=your_key_here", "src/App.jsx": "export default function App() {}"}

  assert resolve_scoped_target_paths("update .env", paths=paths, files_map=files_map) == [".env.example"]


def test_generation_config_uses_opt_in_sampling_and_small_thinking_budget(monkeypatch) -> None:
  monkeypatch.delenv("GEMINI_ENABLE_SAMPLING_OVERRIDES", raising=False)
  monkeypatch.setenv("ENABLE_GEMINI_THINKING_CONFIG", "true")

  config = build_generation_config(response_mime_type="application/json", thinking_level="minimal")

  assert config["responseMimeType"] == "application/json"
  assert "temperature" not in config
  assert "topP" not in config
  assert config["thinkingConfig"] == {"thinkingBudget": 0}


def test_trace_labels_map_to_stages_roles_and_thinking_levels() -> None:
  assert thinking_level_for_trace("route_generation_action") == "minimal"
  assert execution_stage_for_trace("route_generation_action") == "routing"
  assert model_role_for_trace("route_generation_action") == "control"

  assert thinking_level_for_trace("streaming_file_agent") == "low"
  assert execution_stage_for_trace("streaming_file_agent") == "patch"
  assert model_role_for_trace("streaming_file_agent") == "artifact"

  assert thinking_level_for_trace("streaming_file_agent.website_generation") == "medium"
  assert execution_stage_for_trace("streaming_file_agent.website_generation") == "artifact"
  assert model_role_for_trace("streaming_file_agent.website_generation") == "artifact"


def test_json_payload_includes_thinking_config_without_sampling_overrides(monkeypatch) -> None:
  monkeypatch.delenv("GEMINI_ENABLE_SAMPLING_OVERRIDES", raising=False)
  monkeypatch.setenv("ENABLE_GEMINI_THINKING_CONFIG", "true")

  payload = build_generate_json_payload(
    "Classify this request.",
    system_instruction="System",
    google_search=False,
    response_schema=None,
    max_output_tokens=256,
    thinking_level="minimal",
  )

  config = payload["generationConfig"]
  assert config["maxOutputTokens"] == 256
  assert config["thinkingConfig"] == {"thinkingBudget": 0}
  assert "temperature" not in config
  assert "topP" not in config


def test_pricing_counts_thinking_as_output_and_cached_input_separately() -> None:
  cost = estimate_model_usage_cost(
    model="gemini-3.5-flash",
    input_tokens=1000,
    output_tokens=510,
    thought_tokens=339,
    cached_tokens=100,
  )

  assert cost["billable_input_tokens"] == 900
  assert cost["cached_input_tokens"] == 100
  assert cost["billable_output_tokens"] == 849
  assert cost["estimated_cost_usd"] > 0
  assert cost["estimated_credits"] == round(cost["estimated_cost_usd"] * 100, 4)


def test_control_model_policy_keeps_pro_artifact_from_forcing_pro_routing(monkeypatch) -> None:
  monkeypatch.delenv("GEMINI_CONTROL_MODEL", raising=False)
  monkeypatch.delenv("GEMINI_DEFAULT_CONTROL_MODEL", raising=False)

  assert resolve_control_model_for_request("gemini-3.1-pro-preview") == "gemini-3.5-flash"


def test_control_model_policy_respects_explicit_override(monkeypatch) -> None:
  monkeypatch.setenv("GEMINI_CONTROL_MODEL", "gemini-3.5-flash-lite")

  assert resolve_control_model_for_request("gemini-3.1-pro-preview") == "gemini-3.5-flash-lite"


def test_generation_request_exposes_model_policy_and_credit_reservation_fields() -> None:
  request = GenerateRequest(
    prompt="build a dashboard",
    model_policy="auto_staged",
    artifact_model="gemini-3.1-pro-preview",
    request_class="feature_update",
    estimated_credit_reservation=12.5,
  )
  resume = ResumeGenerationRequest(
    prompt="confirm",
    model_policy="auto_staged",
    artifact_model="gemini-3.5-flash",
    request_class="targeted_update",
    estimated_credit_reservation=3.25,
  )

  assert request.model_policy == "auto_staged"
  assert request.artifact_model == "gemini-3.1-pro-preview"
  assert request.request_class == "feature_update"
  assert request.estimated_credit_reservation == 12.5
  assert resume.request_class == "targeted_update"
  assert resume.estimated_credit_reservation == 3.25


def test_admin_user_requests_expose_ai_credit_fields() -> None:
  create = AdminCreateUserRequest(email="user@example.com", password="password123", monthly_ai_credits=750)
  update = AdminUpdateUserRequest(monthly_ai_credits=1250)

  assert create.monthly_ai_credits == 750
  assert update.monthly_ai_credits == 1250


def test_admin_user_creation_rejects_password_as_username() -> None:
  request = AdminCreateUserRequest(
    email="user@example.com",
    password="password123",
    display_name="password123",
  )
  admin = UserContext(id="admin-1", email="admin@example.com", role="admin", display_name="Admin")

  with pytest.raises(HTTPException) as error:
    create_admin_user_payload(request, None, admin)

  assert error.value.status_code == 400
  assert error.value.detail == "Username cannot be the same as the password."


def test_default_credit_reservations_are_route_aware() -> None:
  assert default_credit_reservation_for_route("tiny_chat") == 0.0
  assert default_credit_reservation_for_route("small_code") == 2.0
  assert default_credit_reservation_for_route("targeted_update") == 8.0
  assert default_credit_reservation_for_route("full_generation") == 80.0
  assert default_credit_reservation_for_route("unknown") == 10.0


def test_parallel_worker_step_budgets_cap_total_model_calls(monkeypatch) -> None:
  monkeypatch.setenv("PARALLEL_GENERATION_MODEL_CALL_BUDGET", "10")
  tasks = [
    {"id": "page_1", "kind": "greenfield_page"},
    {"id": "page_2", "kind": "greenfield_page"},
    {"id": "page_3", "kind": "greenfield_page"},
    {"id": "component_1", "kind": "greenfield_component"},
    {"id": "app_shell", "kind": "greenfield_app_shell"},
  ]

  budgets = _assign_worker_step_budgets(tasks, intent="website_generation")

  assert sum(budgets.values()) <= 10
  assert budgets["app_shell"] <= 4
  assert all(value >= 1 for value in budgets.values())


def test_parallel_worker_step_budgets_skip_surplus_tasks(monkeypatch) -> None:
  monkeypatch.setenv("PARALLEL_UPDATE_MODEL_CALL_BUDGET", "4")
  tasks = [{"id": f"task_{index}", "kind": "update"} for index in range(7)]

  budgets = _assign_worker_step_budgets(tasks, intent="website_update")

  assert sum(budgets.values()) <= 4
  assert list(budgets.values()).count(0) == 3


def test_explicit_credit_reservation_overrides_route_default() -> None:
  assert resolve_credit_reservation_estimate("full_generation", 12.5) == 12.5
  assert resolve_credit_reservation_estimate("full_generation", 0) == 0.0
  assert resolve_credit_reservation_estimate("targeted_update", "bad") == 8.0


def test_generation_stream_bridge_forwards_model_policy_fields() -> None:
  captured = {}

  def fake_pipeline(project_id, prompt, context, user, **kwargs):
    captured.update(kwargs)
    return {"ok": True}

  result = call_generation_pipeline_with_current_telemetry(
    fake_pipeline,
    "project-1",
    "build",
    object(),
    type("User", (), {"id": "user-1"})(),
    model="gemini-3.5-flash",
    model_policy="auto_staged",
    artifact_model="gemini-3.1-pro-preview",
    request_class="feature_update",
    estimated_credit_reservation=7.5,
  )

  assert result == {"ok": True}
  assert captured["model_policy"] == "auto_staged"
  assert captured["artifact_model"] == "gemini-3.1-pro-preview"
  assert captured["request_class"] == "feature_update"
  assert captured["estimated_credit_reservation"] == 7.5


def test_confirmed_standalone_code_brief_stays_code_only() -> None:
  route = confirmed_routing_result(
    {
      "operation": "website_update",
      "summary": "Simplify the Python neon number program.",
      "planned_changes": ["Patch the existing Python file."],
    },
    project_files=[{"path": "neon_number.py", "content": "def is_neon_number(n): return True"}],
  )

  assert route["intent"] == "simple_code"
  assert route["next_tool"] == "generate_simple_code_file"
