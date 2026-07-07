from __future__ import annotations

from backend.agents.followup_routing import (
  apply_existing_project_routing_bias,
  is_broad_website_generation_requirement,
  is_explicit_new_project_request,
)
from backend.agents.orchestration.runner import _should_include_existing_simple_code_context
from backend.agents.orchestration.routing import deterministic_routing_result
from backend.agents.orchestration.routing import routing_fallback_after_model_error
from backend.agents.prompt_context import ORCHESTRATOR_CONTEXT_MARKER
from backend.agents.streaming.update_clarification import check_streaming_update_clarification


EXISTING_PROJECT_FILES = [
  {
    "path": "package.json",
    "content": '{"dependencies":{"react":"latest","vite":"latest"}}',
  },
  {
    "path": "index.html",
    "content": '<!doctype html><html><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>',
  },
  {"path": "vite.config.js", "content": "export default defineConfig({ plugins: [] });"},
  {"path": "tailwind.config.js", "content": "module.exports = { content: ['./src/**/*.{js,jsx}'] };"},
  {"path": "postcss.config.js", "content": "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };"},
  {
    "path": "src/main.jsx",
    "content": 'import { createRoot } from "react-dom/client"; createRoot(document.getElementById("root")).render(<App />);',
  },
  {
    "path": "src/index.css",
    "content": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n",
  },
  {"path": "src/App.jsx", "content": "export default function App(){ return <main>Existing site</main>; }"},
]


def test_followup_needs_more_detail_becomes_update_when_code_exists() -> None:
  result = apply_existing_project_routing_bias(
    {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "model",
    },
    prompt="make the colors warmer",
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_update"
  assert result["next_tool"] == "analyze_update_request"


def test_followup_generation_becomes_update_when_code_exists() -> None:
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "model",
    },
    prompt="add a contact page",
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_update"


def test_rich_crm_generation_requirement_stays_generation_when_code_exists() -> None:
  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) After auth provide the onboarding process
  3) once onboarding done provide the dashboard with 4 types report and analytics
  4) provide modules: leads & contact, deals, sales, project, product, main ai chat
  brand guidelines primary black secondary purple others white and grey shadow
  """
  assert is_broad_website_generation_requirement(prompt)
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "model",
    },
    prompt=prompt,
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_generation"


def test_rich_crm_generation_requirement_recovers_from_needs_more_detail_when_code_exists() -> None:
  prompt = """
  Generate the website for CRM with below requirement
  1) Auth
  2) onboarding
  3) dashboard with descriptive diagnostic predictive prescriptive reports
  4) modules: leads contacts deals sales projects products main ai chat
  """
  result = apply_existing_project_routing_bias(
    {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "model",
    },
    prompt=prompt,
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_generation"
  assert result["next_tool"] == "analyze_prompt"


def test_explicit_new_project_request_stays_generation() -> None:
  prompt = "build a brand new site from scratch for a bakery"
  assert is_explicit_new_project_request(prompt)
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "model",
    },
    prompt=prompt,
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_generation"


def test_greenfield_project_keeps_needs_more_detail() -> None:
  result = apply_existing_project_routing_bias(
    {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "model",
    },
    prompt="farm website",
    project_files=[],
  )
  assert result["intent"] == "needs_more_detail"


def test_empty_placeholder_files_do_not_force_update_route() -> None:
  placeholder_files = [
    {"path": "package.json", "content": ""},
    {"path": "index.html", "content": ""},
    {"path": "src/App.jsx", "content": ""},
  ]
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "model",
    },
    prompt="build an AI native farm website",
    project_files=placeholder_files,
  )
  assert result["intent"] == "website_generation"


def test_standalone_code_followup_stays_code_only() -> None:
  result = apply_existing_project_routing_bias(
    {
      "intent": "website_update",
      "next_action": "update_website",
      "next_tool": "analyze_update_request",
      "reason": "model",
    },
    prompt="simplify this neon number code",
    project_files=[{"path": "NeonNumber.java", "content": "public class NeonNumber {}"}],
  )
  assert result["intent"] == "simple_code"
  assert result["next_tool"] == "generate_simple_code_file"


def test_standalone_number_program_does_not_use_deterministic_route() -> None:
  result = deterministic_routing_result("write a code for neon number")

  assert result is None


def test_model_error_fallback_routes_simple_code_without_guessing_website() -> None:
  result = routing_fallback_after_model_error("write a code for neon number in python", RuntimeError("model unavailable"))

  assert result
  assert result["intent"] == "simple_code"
  assert result["next_tool"] == "generate_simple_code_file"


def test_model_error_fallback_routes_document_artifact() -> None:
  result = routing_fallback_after_model_error("Create README.md for installing this API", RuntimeError("model unavailable"))

  assert result
  assert result["intent"] == "document_artifact"
  assert result["next_tool"] == "generate_document_artifact"


def test_model_error_fallback_routes_planning_as_conversation() -> None:
  result = routing_fallback_after_model_error("Plan a rollout strategy for CRM migration", RuntimeError("model unavailable"))

  assert result
  assert result["intent"] == "general_query"


def test_model_error_fallback_routes_latest_research_to_web_search() -> None:
  result = routing_fallback_after_model_error("Research latest vector database pricing and sources", RuntimeError("model unavailable"))

  assert result
  assert result["intent"] == "web_search"


def test_website_context_is_not_misrouted_as_simple_code() -> None:
  result = deterministic_routing_result("write a rust backend for this website")

  assert result is None or result["intent"] != "simple_code"


def test_simple_code_existing_context_is_only_for_update_style_requests() -> None:
  assert _should_include_existing_simple_code_context("write a code for neon number") is False
  assert _should_include_existing_simple_code_context("simplify this neon number code") is True
  assert _should_include_existing_simple_code_context("remove comments from this code") is True


def test_current_user_prompt_strips_orchestrator_context_for_routing_bias() -> None:
  prompt = (
    "change the navbar color\n\n"
    f"{ORCHESTRATOR_CONTEXT_MARKER}\n\n"
    "Previous enhancement-plan context available to the Chief Orchestrator:\n"
    "Update src/App.jsx and src/pages/Home.jsx"
  )
  result = apply_existing_project_routing_bias(
    {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "model",
    },
    prompt=prompt,
    project_files=EXISTING_PROJECT_FILES,
  )
  assert result["intent"] == "website_update"


def test_conversation_context_relaxes_short_followup_clarification() -> None:
  question = check_streaming_update_clarification(
    "make it red",
    intent="website_update",
    project_files=EXISTING_PROJECT_FILES,
    scoped_targets=[],
    has_conversation_context=True,
  )
  assert question is None


def test_short_followup_still_clarifies_without_conversation_context() -> None:
  question = check_streaming_update_clarification(
    "make it red",
    intent="website_update",
    project_files=EXISTING_PROJECT_FILES,
    scoped_targets=[],
    has_conversation_context=False,
  )
  assert question
