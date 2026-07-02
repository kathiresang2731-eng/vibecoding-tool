import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from backend import runtime as runtime_module
from backend.api.generation import (
  append_orchestrator_context,
  original_files_for_generated_paths,
  run_generation_pipeline,
)
from backend.api.run_locks import ProjectGenerationAlreadyRunningError, acquire_project_run_lock, active_project_run
from backend.config import ConfigError, Settings, load_settings
from backend.llm.artifacts import ArtifactValidationError, normalize_artifact_path, validate_project_artifact
from backend.llm.agent_runtime.actions.project_io import interaction_fix_verification_reason
from backend.llm.agent_runtime.fallbacks import is_retriable_scoped_update_guard_error
from backend.llm.chat_history import build_gemini_chat_history_contents, latest_enhancement_context, latest_error_context
from backend.llm.gemini_client.client import build_generate_json_payload
from backend.llm.generator import generate_website, generate_website_or_error, normalize_generation
from backend.llm.orchestrator import GenerationPipelineState, apply_backend_routing_to_response, normalize_routing_result
from backend.llm.orchestration.routing import route_generation_action_tool
from backend.llm.agent_runtime.scoped_update.runtime import run_scoped_update_agent
from backend.llm.prompts import (
  build_conversation_response_prompt,
  build_routing_prompt,
  build_scoped_update_patch_prompt,
  build_simple_code_prompt,
  build_website_prompt,
)
from backend.llm.providers import ARTIFACT_PROVIDER_ROLE, CONTROL_PROVIDER_ROLE, MockProvider
from backend.llm.schema import REQUIRED_RESPONSE_SECTIONS, ResponseContractError
from backend.runtime import PreviewRuntimeError, build_project_preview, prepare_preview_files, validate_preview_dependency_imports


def valid_generation(extra_top_level=False):
  response = {
    "multi_agent_system": {
      "goal": "Build a website.",
      "agents": [
        {
          "name": "Prompt Analyst",
          "role": "Understand prompt",
          "mode": "descriptive",
          "responsibilities": ["Analyze the prompt"],
          "inputs": ["prompt"],
          "outputs": ["brief"],
        }
      ],
      "shared_state": {},
    },
    "gemini_tool_calling_setup": {
      "tool_policy": "Preview-only tools run without approval.",
      "provider": "gemini",
      "tools": [
        {
          "name": "analyze_prompt",
          "purpose": "Analyze the user prompt.",
          "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
          "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
          "approval_required": False,
          "approval_policy": "none",
        }
      ],
      "tool_call_sequence": ["analyze_prompt"],
    },
    "google_adk_usage": {
      "summary": "Hybrid ADK mapping.",
      "adk_agents": [{"adk_type": "LlmAgent", "name": "Prompt Analyst", "purpose": "Analyze prompt"}],
      "runtime_plan": ["Map to real ADK later."],
      "notes": ["No ADK package required now."],
    },
    "orchestration_flow": {
      "steps": [
        {
          "step": 1,
          "name": "Prompt intake",
          "owner_agent": "Prompt Analyst",
          "input": "prompt",
          "actions": ["Analyze"],
          "output": "brief",
        }
      ],
      "generated_website": {
        "title": "Generated Website",
        "headline": "A complete generated website",
        "subheadline": "Generated from one prompt.",
        "primary_cta": "Start",
        "secondary_cta": "Preview",
        "preview_html": "<!doctype html><html><body><main>Generated Website</main></body></html>",
        "theme": {
          "colors": {
            "primary": "#0f766e",
            "secondary": "#2563eb",
            "accent": "#111827",
            "background": "#ffffff",
            "text": "#14212b",
          }
        },
        "sections": [{"name": "Hero", "purpose": "Introduce", "content": "Strong hero copy."}],
        "files": [{"path": "src/App.jsx", "purpose": "Home page", "code": "export default function App() { return <main />; }"}],
      },
    },
    "agent_to_agent_communication": {
      "message_contract": {
        "from_agent": "Prompt Analyst",
        "to_agent": "UI Planner",
        "task": "Plan website",
        "context": {},
        "expected_output": {},
        "confidence": 0.9,
        "risks": [],
      },
      "handoff_rules": ["Each agent passes structured JSON."],
      "example_messages": [{"from_agent": "Prompt Analyst", "to_agent": "UI Planner", "message": {}}],
    },
    "proactive_thinking": {
      "assumptions": ["Single-page website."],
      "missing_information": ["Brand name"],
      "predicted_risks": ["Generic copy"],
      "self_checks": ["Validate sections"],
      "recommended_next_actions": ["Connect preview renderer"],
    },
  }
  if extra_top_level:
    response["site"] = {"should": "be removed"}
  return response


def routing_result(intent="website_generation"):
  mapping = {
    "greeting": {
      "intent": "greeting",
      "next_action": "respond_and_collect_website_brief",
      "next_tool": "handle_greeting",
      "reason": "The routing prompt selected greeting handling.",
    },
    "needs_more_detail": {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "The routing prompt selected detail collection.",
    },
    "project_info": {
      "intent": "project_info",
      "next_action": "summarize_current_project",
      "next_tool": "summarize_current_project",
      "reason": "The routing prompt selected current project summary.",
    },
    "simple_code": {
      "intent": "simple_code",
      "next_action": "write_standalone_code_file",
      "next_tool": "generate_simple_code_file",
      "reason": "The routing prompt selected standalone code generation.",
    },
    "website_generation": {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "The routing prompt selected website generation.",
    },
    "website_update": {
      "intent": "website_update",
      "next_action": "update_website",
      "next_tool": "analyze_update_request",
      "reason": "The routing prompt selected website update.",
    },
  }
  return mapping[intent]


class FakeGeminiClient:
  provider_role = ARTIFACT_PROVIDER_ROLE

  def __init__(self, payload, conversation_payload=None, routing_payload=None, routing_payloads=None):
    self.payload = payload
    self.conversation_payload = conversation_payload or {
      "type": "greeting",
      "message": "Dynamic test response from the conversation agent.",
      "next_prompt_guidance": [
        "Tell me the website type.",
        "Share the brand name and target audience.",
        "List sections, style, and must-have features.",
      ],
    }
    self.routing_payload = routing_payload or routing_result("website_generation")
    self.routing_payloads = list(routing_payloads or [])
    self.received_prompt = ""
    self.call_count = 0
    self.prompts = []
    self.system_instructions = []
    self.trace_labels = []

  def generate_json(self, prompt, **kwargs):
    self.call_count += 1
    self.received_prompt = prompt
    self.prompts.append(prompt)
    self.system_instructions.append(kwargs.get("system_instruction"))
    self.trace_labels.append(kwargs.get("trace_label"))
    if "You are the route_generation_action tool" in prompt or "route_generation_action output" in prompt:
      if self.routing_payloads:
        return self.routing_payloads.pop(0)
      return self.routing_payload
    if "Write the assistant response for Worktual AI Dev" in prompt:
      return self.conversation_payload
    return self.payload


class FakeControlClient(FakeGeminiClient):
  provider_role = CONTROL_PROVIDER_ROLE


class LLMContractTests(unittest.TestCase):
  def test_valid_response_passes_and_removes_extra_top_level_keys(self):
    result = normalize_generation(valid_generation(extra_top_level=True))
    self.assertEqual(list(result.keys()), REQUIRED_RESPONSE_SECTIONS)
    self.assertNotIn("site", result)

  def test_missing_required_top_level_section_fails(self):
    response = valid_generation()
    response.pop("multi_agent_system")
    with self.assertRaises(ResponseContractError):
      normalize_generation(response)

  def test_missing_generated_website_fails(self):
    response = valid_generation()
    response["orchestration_flow"].pop("generated_website")
    with self.assertRaises(ResponseContractError):
      normalize_generation(response)

  def test_split_provider_legacy_generation_returns_six_section_response(self):
    control = FakeControlClient(valid_generation())
    artifact = FakeGeminiClient(valid_generation())
    result = generate_website(
      "Build a website for a B2B SaaS CRM",
      control_provider=control,
      artifact_provider=artifact,
      allow_legacy_fallback=True,
    )
    self.assertEqual(list(result.keys()), REQUIRED_RESPONSE_SECTIONS)
    self.assertIn("gemini_tool_calling_setup", result)
    self.assertEqual(result["gemini_tool_calling_setup"]["provider"], "gemini-native-control-artifact")
    self.assertEqual(result["gemini_tool_calling_setup"]["control_provider"], "FakeControlClient")
    self.assertEqual(result["gemini_tool_calling_setup"]["artifact_provider"], "FakeGeminiClient")

  def test_website_generation_requires_real_agent_runtime_unless_legacy_enabled(self):
    with self.assertRaises(ResponseContractError):
      generate_website(
        "Build a website for a B2B SaaS CRM",
        control_provider=FakeControlClient(valid_generation()),
        artifact_provider=FakeGeminiClient(valid_generation()),
      )

  def test_generate_website_executes_required_backend_pipeline_order(self):
    control = FakeControlClient(valid_generation())
    artifact = FakeGeminiClient(valid_generation())
    result = generate_website(
      "Build a website for a B2B SaaS CRM",
      control_provider=control,
      artifact_provider=artifact,
      allow_legacy_fallback=True,
    )
    execution = result["proactive_thinking"]["backend_execution"]
    completed_stage_names = [stage["stage"] for stage in execution["completed_stages"]]
    graph = execution["orchestration_graph"]
    agentic_flow = execution["agentic_flow"]
    a2a_communication = execution["a2a_communication"]
    google_adk_runtime = execution["google_adk_runtime"]
    langchain_runtime = execution["langchain_runtime"]

    self.assertEqual(execution["pipeline_stage_order"], REQUIRED_RESPONSE_SECTIONS)
    self.assertEqual(completed_stage_names, REQUIRED_RESPONSE_SECTIONS)
    self.assertIn(
      graph["runtime"],
      ["worktual-python-orchestration-graph", "worktual-langgraph-orchestration-graph"],
    )
    self.assertEqual(graph["branch"], "website_generation")
    self.assertEqual(graph["nodes"][0]["stage"], "route_generation_action")
    self.assertEqual(graph["nodes"][0]["output"]["intent"], "website_generation")
    self.assertEqual([node["stage"] for node in graph["nodes"][1:]], REQUIRED_RESPONSE_SECTIONS)
    self.assertEqual(agentic_flow["runtime"], "worktual-python-agentic-flow")
    self.assertEqual(agentic_flow["branch"], "website_generation")
    self.assertGreater(agentic_flow["step_count"], 1)
    self.assertEqual(a2a_communication["runtime"], "worktual-python-a2a-communication")
    self.assertEqual(a2a_communication["branch"], "website_generation")
    self.assertEqual(a2a_communication["message_count"], agentic_flow["handoff_count"])
    self.assertEqual(a2a_communication["validation_status"], "valid")
    self.assertEqual(google_adk_runtime["runtime"], "worktual-google-adk-runtime")
    self.assertEqual(google_adk_runtime["validation_status"], "valid")
    self.assertGreater(google_adk_runtime["event_count"], 1)
    self.assertEqual(langchain_runtime["runtime"], "worktual-langchain-langgraph-runtime")
    self.assertEqual(langchain_runtime["validation_status"], "valid")
    self.assertGreater(langchain_runtime["node_count"], 1)
    self.assertIn("agentic_runtime", result["multi_agent_system"])
    self.assertIn("a2a_runtime", result["multi_agent_system"])
    self.assertIn("langchain_runtime", result["multi_agent_system"])
    self.assertIn("runtime", result["google_adk_usage"])
    self.assertEqual(result["google_adk_usage"]["runtime"]["validation"]["status"], "valid")
    self.assertIn("langchain_runtime", result["proactive_thinking"])
    self.assertEqual(result["proactive_thinking"]["langchain_runtime"]["validation"]["status"], "valid")
    self.assertIn("agentic_handoffs", result["agent_to_agent_communication"])
    self.assertIn("a2a_runtime", result["agent_to_agent_communication"])
    self.assertEqual(result["agent_to_agent_communication"]["a2a_runtime"]["validation"]["status"], "valid")
    self.assertIn("sender", result["agent_to_agent_communication"]["message_contract"])
    self.assertIn("receiver", result["agent_to_agent_communication"]["message_contract"])
    self.assertIn("next_action", result["agent_to_agent_communication"]["message_contract"])
    self.assertIn("handoff_contract_fields", result["multi_agent_system"]["a2a_runtime"])
    self.assertEqual(result["multi_agent_system"]["intent"], "website_generation")
    self.assertEqual(result["gemini_tool_calling_setup"]["tool_call_sequence"][0], "route_generation_action")
    self.assertIn("Backend execution pipeline context", artifact.received_prompt)

  def test_runtime_projection_failure_does_not_fail_completed_generation(self):
    control = FakeControlClient(valid_generation())
    artifact = FakeGeminiClient(valid_generation())

    with patch("backend.agents.orchestration.live_runtime_trace.build_a2a_communication", side_effect=RuntimeError("projection broke")):
      result = generate_website(
        "Build a website for a B2B SaaS CRM",
        control_provider=control,
        artifact_provider=artifact,
        allow_legacy_fallback=True,
      )

    self.assertEqual(result["multi_agent_system"]["intent"], "website_generation")
    self.assertEqual(result["orchestration_flow"]["generated_website"]["title"], "Generated Website")
    projection_error = result["proactive_thinking"]["backend_execution"]["runtime_projection_error"]
    self.assertEqual(projection_error["status"], "skipped")
    self.assertIn("projection broke", projection_error["reason"])

  def test_real_runtime_tool_sequence_does_not_merge_legacy_pseudo_tools(self):
    state = GenerationPipelineState(
      user_prompt="Build a CRM website",
      intent="website_generation",
      routing_result={"intent": "website_generation", "next_tool": "analyze_prompt", "reason": "ready"},
    )
    state.response = {
      "multi_agent_system": {
        "agentic_runtime": {
          "tool_source_of_truth": True,
          "agents": [{"name": "Code Agent"}],
          "steps": [{"agent": "Code Agent", "action": "write_project_files"}],
          "tool_calls": [
            {"name": "READ_PROJECT_FILES"},
            {"name": "LOAD_PROJECT_MEMORY"},
            {"name": "VALIDATE_PROJECT_ARTIFACT"},
            {"name": "BUILD_STAGED_PROJECT_PREVIEW"},
            {"name": "WRITE_PROJECT_FILES"},
          ],
        }
      },
      "gemini_tool_calling_setup": {
        "tools": [{"name": "analyze_prompt"}],
        "tool_call_sequence": ["analyze_prompt", "generate_website_files"],
      },
    }

    apply_backend_routing_to_response(state)

    sequence = state.response["gemini_tool_calling_setup"]["tool_call_sequence"]
    self.assertEqual(
      sequence,
      [
        "route_generation_action",
        "READ_PROJECT_FILES",
        "LOAD_PROJECT_MEMORY",
        "VALIDATE_PROJECT_ARTIFACT",
        "BUILD_STAGED_PROJECT_PREVIEW",
        "WRITE_PROJECT_FILES",
      ],
    )
    self.assertNotIn("analyze_prompt", sequence)
    self.assertNotIn("generate_website_files", sequence)

  def test_greeting_prompt_uses_greeting_agent_and_dynamic_conversation_response(self):
    control = FakeControlClient(valid_generation(), routing_payload=routing_result("greeting"))
    artifact = FakeGeminiClient(valid_generation())
    result = generate_website(
      "hi",
      control_provider=control,
      artifact_provider=artifact,
    )

    self.assertEqual(list(result.keys()), REQUIRED_RESPONSE_SECTIONS)
    self.assertEqual(result["multi_agent_system"]["intent"], "greeting")
    self.assertEqual(result["multi_agent_system"]["active_agent"], "Greeting Handler Agent")
    self.assertEqual(result["multi_agent_system"]["conversation_response"]["message"], "Dynamic test response from the conversation agent.")
    self.assertEqual(result["gemini_tool_calling_setup"]["tool_call_sequence"], ["route_generation_action", "handle_greeting"])
    self.assertEqual(result["gemini_tool_calling_setup"]["runtime_trace"]["tool_calls"][0]["name"], "route_generation_action")
    self.assertEqual(result["gemini_tool_calling_setup"]["runtime_trace"]["tool_calls"][1]["name"], "handle_greeting")
    self.assertEqual(control.call_count, 1)
    self.assertEqual(artifact.call_count, 0)
    self.assertIn("Write the assistant response for Worktual AI Dev", control.received_prompt)
    self.assertEqual(control.trace_labels, ["route_generation_action", "handle_greeting"])

  def test_short_non_greeting_prompt_uses_detail_request_tool_not_keyword_routing(self):
    control = FakeControlClient(valid_generation(), routing_payload=routing_result("needs_more_detail"))
    artifact = FakeGeminiClient(valid_generation())
    result = generate_website(
      "crm",
      control_provider=control,
      artifact_provider=artifact,
    )

    self.assertEqual(list(result.keys()), REQUIRED_RESPONSE_SECTIONS)
    self.assertEqual(result["multi_agent_system"]["intent"], "needs_more_detail")
    self.assertEqual(result["gemini_tool_calling_setup"]["tool_call_sequence"], ["route_generation_action", "request_website_details"])
    self.assertEqual(result["multi_agent_system"]["conversation_response"]["message"], "Dynamic test response from the conversation agent.")
    self.assertEqual(control.call_count, 2)
    self.assertEqual(artifact.call_count, 0)

  def test_invalid_routing_output_is_repaired_before_returning_error(self):
    control = FakeControlClient(
      valid_generation(),
      routing_payloads=[
        {"intent": "greeting_only", "reason": "Invalid enum"},
        routing_result("greeting"),
      ],
    )
    artifact = FakeGeminiClient(valid_generation())
    result = generate_website(
      "hello, please help me start a website brief",
      control_provider=control,
      artifact_provider=artifact,
    )

    self.assertEqual(result["multi_agent_system"]["intent"], "greeting")
    self.assertEqual(result["gemini_tool_calling_setup"]["tool_call_sequence"], ["route_generation_action", "handle_greeting"])
    self.assertIn("Repair the output", control.prompts[1])

  def test_generate_website_or_error_returns_success_for_split_providers(self):
    status, payload = generate_website_or_error(
      "Build a website for a B2B SaaS CRM",
      control_provider=FakeControlClient(valid_generation()),
      artifact_provider=FakeGeminiClient(valid_generation()),
      allow_legacy_fallback=True,
    )
    self.assertEqual(status, 200)
    self.assertEqual(list(payload.keys()), REQUIRED_RESPONSE_SECTIONS)

  def test_website_update_uses_update_branch_and_artifact_trace(self):
    control = FakeControlClient(valid_generation(), routing_payload=routing_result("website_update"))
    artifact = FakeGeminiClient(valid_generation())

    result = generate_website(
      "Update the existing farm website hero CTA",
      control_provider=control,
      artifact_provider=artifact,
      allow_legacy_fallback=True,
    )

    self.assertEqual(result["multi_agent_system"]["intent"], "website_update")
    self.assertEqual(result["proactive_thinking"]["backend_execution"]["orchestration_graph"]["branch"], "website_update")
    self.assertEqual(result["multi_agent_system"]["agentic_runtime"]["branch"], "website_update")
    self.assertEqual(artifact.call_count, 1)
    self.assertEqual(artifact.trace_labels, ["update_website_artifact"])
    self.assertIn("Current artifact mode: website_update", artifact.received_prompt)

  def test_routing_normalizer_uses_model_selected_intent_for_pagination_request(self):
    raw_route = {
      "intent": "website_update",
      "next_action": "update_website",
      "next_tool": "analyze_update_request",
      "reason": "Model selected update for pagination.",
    }

    result = normalize_routing_result(
      raw_route,
      prompt="add the pagination in the website and each page must be have 20 products",
    )

    self.assertEqual(result["intent"], "website_update")
    self.assertEqual(result["next_action"], "update_website")
    self.assertEqual(result["next_tool"], "analyze_update_request")
    self.assertEqual(result["reason"], "Model selected update for pagination.")

  def test_routing_normalizer_does_not_override_model_intent_with_keywords(self):
    raw_route = {
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "Model asked for more details.",
    }

    result = normalize_routing_result(
      raw_route,
      prompt="increase the each page size to 25",
    )

    self.assertEqual(result["intent"], "needs_more_detail")
    self.assertEqual(result["next_tool"], "request_website_details")

  def test_strict_artifact_validation_rejects_missing_app_entry(self):
    response = valid_generation()
    generated = response["orchestration_flow"]["generated_website"]
    generated["files"] = [{"path": "src/Other.jsx", "purpose": "Other", "code": "export default function Other() {}"}]

    with self.assertRaises(ArtifactValidationError):
      validate_project_artifact(generated)

  def test_artifact_validation_preserves_enterprise_generation_metadata(self):
    response = valid_generation()
    generated = response["orchestration_flow"]["generated_website"]
    generated["design_tokens"] = {
      "colors": {"primary": {"value": "#0f766e", "contrast_ratio": "7.1:1"}},
      "layout": {"philosophy": "Operational SaaS"},
    }
    generated["component_manifest"] = [
      {
        "name": "EnterpriseComplianceFooter",
        "path": "src/components/EnterpriseComplianceFooter.jsx",
        "states": ["loading", "error", "hover", "active", "responsive"],
      }
    ]
    generated["seo"] = {"json_ld_schema_type": "SoftwareApplication"}
    generated["compliance"] = {"accessibility": ["semantic HTML5 and aria-label checks"]}

    result = validate_project_artifact(generated)

    self.assertEqual(result["design_tokens"]["layout"]["philosophy"], "Operational SaaS")
    self.assertEqual(result["component_manifest"][0]["name"], "EnterpriseComplianceFooter")
    self.assertEqual(result["seo"]["json_ld_schema_type"], "SoftwareApplication")
    self.assertIn("accessibility", result["compliance"])

  def test_gemini_payload_uses_enterprise_system_instruction_by_default(self):
    payload = build_generate_json_payload(
      "Generate a site",
      system_instruction=None,
      google_search=False,
      response_schema=None,
      max_output_tokens=None,
    )

    system_text = payload["systemInstruction"]["parts"][0]["text"]
    lower_system_text = system_text.lower()
    self.assertIn("Enterprise-Grade, AI-Native Web Generation Platform", system_text)
    self.assertIn("Component-driven architecture", system_text)
    self.assertIn("Design tokens", system_text)
    self.assertIn("user provides brand values", lower_system_text)
    self.assertIn("infer an appropriate token system dynamically", system_text)
    self.assertIn("never use a static default palette", lower_system_text)
    self.assertIn("SEARCH/REPLACE blocks", system_text)

  def test_gemini_payload_preserves_explicit_control_system_instruction(self):
    payload = build_generate_json_payload(
      "Route this prompt",
      system_instruction="Return routing JSON only.",
      google_search=False,
      response_schema=None,
      max_output_tokens=None,
    )

    self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Return routing JSON only.")

  def test_routing_prompt_treats_current_website_information_as_project_info(self):
    prompt = build_routing_prompt("give me the information about this website")

    self.assertIn('"project_info"', prompt)
    self.assertIn('"give me the information about this website" => project_info', prompt)
    self.assertIn("no confirmation", prompt)
    self.assertIn("no file writes", prompt)

  def test_project_info_routing_normalizes_to_non_mutating_summary_tool(self):
    normalized = normalize_routing_result(
      {
        "intent": "project_info",
        "next_action": "summarize_current_project",
        "next_tool": "summarize_current_project",
        "reason": "The user asked for information about the current website.",
      },
      prompt="give me the information about this website",
    )

    self.assertEqual(normalized["intent"], "project_info")
    self.assertEqual(normalized["next_action"], "summarize_current_project")
    self.assertEqual(normalized["next_tool"], "summarize_current_project")

  def test_last_update_status_question_routes_to_project_info_through_model(self):
    prompt = append_orchestrator_context(
      "what you done in the last update?",
      enhancement_context="The user previously asked to add 5 different tigers to the animals page.",
      error_context="Scoped update returned no effective file changes.",
    )

    class RecordingClient:
      calls = 0

      def generate_json(self, *_args, **_kwargs):
        self.calls += 1
        return {
          "intent": "project_info",
          "reason": "The user asked for the status of the previous update.",
        }

    client = RecordingClient()
    routed = route_generation_action_tool(prompt, client)

    self.assertEqual(client.calls, 1)
    self.assertEqual(routed["intent"], "project_info")
    self.assertEqual(routed["next_tool"], "summarize_current_project")
    self.assertIn("previous update", routed["reason"].lower())

  def test_routing_prompt_treats_understand_error_as_project_info(self):
    prompt = build_routing_prompt("Uncaught TypeError: v.map is not a function. Understand this error")

    self.assertIn('"understand this error" => project_info', prompt)
    self.assertIn("only asks to understand, explain", prompt)
    self.assertIn("Use website_update only", prompt)

  def test_project_info_conversation_prompt_requests_summary_not_confirmation(self):
    prompt = build_conversation_response_prompt(
      "give me the information about this website",
      intent="project_info",
      selected_tool="summarize_current_project",
      routing_result=routing_result("project_info"),
    )

    self.assertIn("summarize the CURRENT live website", prompt)
    self.assertIn("enhancement plan", prompt)
    self.assertIn("Do not ask", prompt)
    self.assertIn("for confirmation", prompt)

  def test_routing_prompt_treats_followup_enhancement_plan_as_update(self):
    prompt = build_routing_prompt("implement those enhancement ideas")

    self.assertIn("previous enhancement idea", prompt)
    self.assertIn('"website_update"', prompt)

  def test_orchestrator_context_does_not_route_followups_in_python(self):
    prompt = append_orchestrator_context(
      "try again",
      error_context="Uncaught TypeError: v.map is not a function",
      enhancement_context="Improve the hero section.",
    )

    self.assertIn("Additional conversation context for model routing and planning", prompt)
    self.assertIn("Previous runtime/build error context", prompt)
    self.assertIn("Previous enhancement-plan context", prompt)
    self.assertIn("Use it only if the current user request refers to or depends on it", prompt)
    self.assertNotIn("Treat this as the current error-fix request", prompt)

  def test_simple_code_diff_scope_ignores_unrelated_existing_files(self):
    scoped = original_files_for_generated_paths(
      [
        {"path": "neon_number.py", "content": "print('existing')\n"},
        {"path": "armstrong_number.py", "content": "print('old')\n"},
      ],
      [{"path": "armstrong_number.py", "code": "print('new')\n"}],
    )

    self.assertEqual(scoped, [{"path": "armstrong_number.py", "content": "print('old')\n"}])

  def test_routing_prompt_treats_backend_db_requests_as_project_work(self):
    prompt = build_routing_prompt("write a python backend with FastAPI and Postgres for this website")

    self.assertIn("backend route", prompt)
    self.assertIn("PostgreSQL connection", prompt)
    self.assertIn('"write a python backend with FastAPI and Postgres for this website" => website_update', prompt)
    self.assertIn('"create a FastAPI backend with PostgreSQL for contacts, deals, and projects" => website_generation', prompt)

  def test_website_prompt_supports_backend_database_artifacts_without_static_filenames(self):
    prompt = build_website_prompt("write a python backend with FastAPI and Postgres for contacts")

    self.assertIn("Backend/API/database", prompt)
    self.assertIn("infer", prompt)
    self.assertIn("Do not rely on a static backend filename list", prompt)
    self.assertIn("FastAPI + PostgreSQL", prompt)
    self.assertIn("Derive table names, fields, relationships, route names", prompt)
    self.assertNotIn("backend/main.py", prompt)
    self.assertNotIn("files array must include src/App.jsx", prompt)

  def test_validate_project_artifact_allows_backend_only_fastapi_files(self):
    generated = valid_generation()["orchestration_flow"]["generated_website"]
    generated["files"] = [
      {
        "path": "backend/main.py",
        "purpose": "FastAPI app entrypoint",
        "code": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health():\n  return {'status': 'ok'}\n",
      },
      {
        "path": "backend/database.py",
        "purpose": "PostgreSQL database connection",
        "code": "from sqlalchemy import create_engine\nengine = create_engine('postgresql://user:pass@localhost/db')\n",
      },
      {
        "path": "requirements.txt",
        "purpose": "Backend dependencies",
        "code": "fastapi\nuvicorn\nsqlalchemy\npsycopg2-binary\n",
      },
      {
        "path": ".env.example",
        "purpose": "Environment template",
        "code": "DATABASE_URL=postgresql://user:password@localhost:5432/app\n",
      },
    ]

    result = validate_project_artifact(generated)

    self.assertIn("backend/main.py", [file_item["path"] for file_item in result["files"]])

  def test_latest_enhancement_context_extracts_previous_model_plan(self):
    messages = [
      {"role": "user", "content": "give me information about this website"},
      {"role": "model", "content": "Summary...\nEnhancement plan:\n1. Improve hero\n2. Add testimonials"},
      {"role": "user", "content": "implement those ideas"},
    ]

    context = latest_enhancement_context(messages)

    self.assertIn("Enhancement plan", context)
    self.assertIn("Improve hero", context)

  def test_latest_error_context_extracts_previous_runtime_stack(self):
    messages = [
      {"role": "user", "content": "update the onboarding page"},
      {
        "role": "user",
        "content": "Uncaught TypeError: Cannot read properties of undefined (reading 'name') at Dashboard.jsx",
      },
      {"role": "model", "content": "Generation failed: The scoped update was blocked by project safety checks."},
      {"role": "user", "content": "try again"},
    ]

    context = latest_error_context(messages)

    self.assertIn("Cannot read properties", context)
    self.assertIn("Dashboard.jsx", context)

  def test_scoped_update_prompt_requires_micro_step_search_replace_edits(self):
    prompt = build_scoped_update_patch_prompt(
      "Implement enhancement step 1",
      update_analysis={"candidate_files": ["src/App.jsx"], "candidate_new_files": []},
      candidate_files=[{"path": "src/App.jsx", "content": "export default function App() { return null; }"}],
      code_search_matches=[],
    )

    self.assertIn("one micro-step", prompt)
    self.assertIn("current approved candidate file", prompt)
    self.assertIn("Prefer line-level SEARCH/REPLACE edits", prompt)
    self.assertIn("needs_scope_expansion", prompt)
    self.assertIn("requested_files", prompt)

  def test_scoped_update_agent_sends_one_full_file_per_model_step(self):
    class InspectingProvider:
      def generate_json(self, prompt, **kwargs):
        self.prompt = prompt
        return {
          "status": "completed",
          "summary": "Updated app.",
          "edits": [
            {
              "path": "src/App.jsx",
              "search": "app",
              "replace": "updated app",
              "expected_replacements": 1,
            }
          ],
          "changed_files": [],
          "clarification_question": "",
        }

    provider = InspectingProvider()
    run_scoped_update_agent(
      provider,
      prompt="Improve the dashboard",
      update_analysis={
        "update_mode": "feature_patch",
        "candidate_files": ["src/App.jsx", "src/pages/Dashboard.jsx"],
        "candidate_new_files": [],
      },
      existing_files=[
        {"path": "src/App.jsx", "content": "app"},
        {"path": "src/pages/Dashboard.jsx", "content": "dashboard"},
      ],
      code_search_matches=[],
    )

    allowed_section = provider.prompt.split("Allowed existing files with complete current contents:", 1)[1].split("Relevant code-search matches:", 1)[0]
    self.assertIn("src/App.jsx", allowed_section)
    self.assertNotIn("src/pages/Dashboard.jsx", allowed_section)

  def test_interaction_fix_requires_detectable_event_wiring_before_commit(self):
    reason = interaction_fix_verification_reason(
      {
        "prompt": "the save button is not working fix it",
        "changed_file_paths": ["src/App.jsx"],
        "candidate_files": [{"path": "src/App.jsx", "content": "<button>Save</button>"}],
      }
    )

    self.assertIn("event wiring", reason)

    ok = interaction_fix_verification_reason(
      {
        "prompt": "the save button is not working fix it",
        "changed_file_paths": ["src/App.jsx"],
        "candidate_files": [{"path": "src/App.jsx", "content": "<button onClick={handleSave}>Save</button>"}],
      }
    )
    self.assertEqual(ok, "")

  def test_scope_boundary_errors_are_retriable_for_split_updates(self):
    self.assertTrue(
      is_retriable_scoped_update_guard_error(
        RuntimeError("Scoped update attempted to edit unapproved file src/pages/Deals.jsx.")
      )
    )

  def test_gemini_payload_can_include_project_chat_history_before_latest_prompt(self):
    history = [
      {"role": "user", "parts": [{"text": "First user message"}]},
      {"role": "model", "parts": [{"text": "First AI response"}]},
    ]
    payload = build_generate_json_payload(
      "Latest user message",
      system_instruction=None,
      google_search=False,
      response_schema=None,
      max_output_tokens=None,
      chat_history=history,
    )

    self.assertEqual(payload["contents"], [
      {"role": "user", "parts": [{"text": "First user message"}]},
      {"role": "model", "parts": [{"text": "First AI response"}]},
      {"role": "user", "parts": [{"text": "Latest user message"}]},
    ])

  def test_chat_history_pruning_keeps_recent_turns_and_strips_old_code_blocks(self):
    messages = []
    for index in range(14):
      messages.append({"role": "user", "content": f"User turn {index}\n```jsx\nold code {index}\n```"})
      messages.append({"role": "model", "content": f"Model turn {index}\n```jsx\nold response code {index}\n```"})

    contents = build_gemini_chat_history_contents(messages, recent_turns=10)

    self.assertEqual(contents[0]["role"], "user")
    self.assertIn("Earlier conversation summary", contents[0]["parts"][0]["text"])
    self.assertIn("[code block omitted from older chat memory]", contents[0]["parts"][0]["text"])
    self.assertEqual(contents[-1]["role"], "model")
    self.assertIn("Model turn 13", contents[-1]["parts"][0]["text"])

  def test_artifact_path_validation_rejects_traversal_and_env_files(self):
    with self.assertRaises(ArtifactValidationError):
      normalize_artifact_path("../secrets.txt")
    with self.assertRaises(ArtifactValidationError):
      normalize_artifact_path("../package.json")
    with self.assertRaises(ArtifactValidationError):
      normalize_artifact_path(".env")

  def test_config_requires_database_url_for_platform_runtime(self):
    with self.assertRaises(ConfigError):
      load_settings(require_database=True, env={})

  def test_config_uses_server_only_gemini_key(self):
    settings = load_settings(
      require_database=True,
      env={
        "DATABASE_URL": "postgres://example",
        "VITE_GEMINI_API_KEY": "client-visible",
        "GEMINI_API_KEY": "server-only",
      },
    )
    self.assertEqual(settings.gemini_api_key, "server-only")

  def test_mock_provider_generation_returns_strict_artifact(self):
    result = generate_website(
      "Build a website for a local bakery with menu, gallery, testimonials, contact form, and warm modern style",
      provider=MockProvider(),
      allow_legacy_fallback=True,
    )
    generated = result["orchestration_flow"]["generated_website"]

    self.assertEqual(result["multi_agent_system"]["intent"], "website_generation")
    self.assertIn("src/App.jsx", [file["path"] for file in generated["files"]])

  def test_generate_stream_emits_live_progress_before_complete(self):
    from backend import main as backend_main

    original_pipeline = backend_main.run_generation_pipeline

    def fake_pipeline(project_id, prompt, context, user, *, progress_callback=None):
      progress_callback({"step": "routing.started", "message": "Routing prompt", "status": "running"})
      progress_callback({"step": "routing.completed", "message": "Routing complete", "status": "completed"})
      return {
        "generation_run": {"id": "run-1"},
        "generation": {"multi_agent_system": {"conversation_response": {"message": "ok"}}},
        "files": [],
        "local_sync": None,
        "local_sync_error": None,
      }

    async def post_generate_stream():
      transport = httpx.ASGITransport(app=backend_main.app)
      async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
          "/api/projects/project-1/generate-stream",
          json={"prompt": "Build a website"},
        )

    try:
      backend_main.run_generation_pipeline = fake_pipeline
      backend_main.app.dependency_overrides[backend_main.get_context] = lambda: object()
      backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: type("User", (), {"id": "user-1"})()
      response = asyncio.run(post_generate_stream())
      lines = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    finally:
      backend_main.run_generation_pipeline = original_pipeline
      backend_main.app.dependency_overrides.clear()

    self.assertEqual(response.status_code, 200)
    self.assertGreaterEqual(len(lines), 3)
    self.assertEqual(lines[0]["type"], "progress")
    self.assertEqual(lines[0]["step"], "routing.started")
    self.assertEqual(lines[1]["type"], "progress")
    self.assertEqual(lines[-1]["type"], "complete")

  def test_generate_stream_accepts_chat_message_payload_without_422(self):
    from backend import main as backend_main

    original_pipeline = backend_main.run_generation_pipeline
    captured = {}

    def fake_pipeline(project_id, prompt, context, user, *, progress_callback=None, model=None):
      captured["prompt"] = prompt
      captured["model"] = model
      return {
        "generation_run": {"id": "run-1"},
        "generation": {"multi_agent_system": {"conversation_response": {"message": "ok"}}},
        "files": [],
        "local_sync": None,
        "local_sync_error": None,
      }

    async def post_generate_stream():
      transport = httpx.ASGITransport(app=backend_main.app)
      async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
          "/api/projects/project-1/generate-stream",
          json={"message": "hi", "model": "server-default"},
        )

    try:
      backend_main.run_generation_pipeline = fake_pipeline
      backend_main.app.dependency_overrides[backend_main.get_context] = lambda: object()
      backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: type("User", (), {"id": "user-1"})()
      response = asyncio.run(post_generate_stream())
    finally:
      backend_main.run_generation_pipeline = original_pipeline
      backend_main.app.dependency_overrides.clear()

    self.assertEqual(response.status_code, 200)
    self.assertEqual(captured["prompt"], "hi")
    self.assertIsNone(captured["model"])

  def test_generate_stream_empty_payload_returns_400_not_422(self):
    from backend import main as backend_main

    async def post_generate_stream():
      transport = httpx.ASGITransport(app=backend_main.app)
      async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post("/api/projects/project-1/generate-stream", json={})

    try:
      backend_main.app.dependency_overrides[backend_main.get_context] = lambda: object()
      backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: type("User", (), {"id": "user-1"})()
      response = asyncio.run(post_generate_stream())
    finally:
      backend_main.app.dependency_overrides.clear()

    self.assertEqual(response.status_code, 400)
    self.assertIn("Prompt is empty", response.json()["detail"])

  def test_project_generation_lock_blocks_duplicate_project_run(self):
    with acquire_project_run_lock("project-lock", user_id="user-1") as run:
      active = active_project_run("project-lock")
      self.assertIsNotNone(active)
      self.assertEqual(active["run_id"], run.run_id)
      with self.assertRaises(ProjectGenerationAlreadyRunningError):
        with acquire_project_run_lock("project-lock", user_id="user-1"):
          pass

    self.assertIsNone(active_project_run("project-lock"))

  def test_greeting_prompt_uses_deterministic_tiny_chat_and_no_file_updates(self):
    class FakeStore:
      def __init__(self):
        self.chat_messages = []
        self.tool_calls = []
        self.agent_messages = []

      def get_project(self, project_id, user):
        return {"id": project_id, "name": "Test project", "local_path": None}

      def list_files(self, project_id, user):
        return [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]

      def list_project_chat_messages(self, project_id, user, limit=None):
        return []

      def record_project_chat_message(self, project_id, user, *, role, content, metadata=None):
        self.chat_messages.append({"role": role, "content": content, "metadata": metadata or {}})

      def create_agent_run(self, project_id, user, **kwargs):
        return {"id": "agent-run-1", "project_id": project_id, **kwargs}

      def create_generation_run(self, project_id, user, **kwargs):
        return {"id": "generation-run-1", "project_id": project_id, **kwargs}

      def record_agent_message(self, *args, **kwargs):
        self.agent_messages.append(kwargs)

      def record_tool_call(self, *args, **kwargs):
        self.tool_calls.append(kwargs)

      def record_generation_checkpoint(self, *args, **kwargs):
        pass

      def upsert_memory_item(self, *args, **kwargs):
        pass

      def complete_agent_run(self, agent_run_id, user, **kwargs):
        return {"id": agent_run_id, **kwargs}

    def greeting_provider(*args, **kwargs):
      return MockProvider(
        routing_payload={
          "intent": "greeting",
          "next_action": "respond_and_collect_website_brief",
          "next_tool": "handle_greeting",
          "reason": "The user is opening the conversation with a greeting.",
        },
        conversation_payload={
          "type": "greeting",
          "message": "Hi. Tell me what you want to build or update next.",
          "next_prompt_guidance": ["Describe the website, app, or code you want."],
        },
      )

    with patch("backend.api.generation.GeminiProvider", greeting_provider), patch("backend.main.GeminiProvider", greeting_provider):
      store = FakeStore()
      result = run_generation_pipeline(
        "project-1",
        "hi",
        SimpleNamespace(store=store, settings=SimpleNamespace()),
        SimpleNamespace(id="user-1"),
    )

    self.assertEqual(result["generation"]["multi_agent_system"]["intent"], "greeting")
    self.assertIsNone(result["agent_run"])
    self.assertEqual(result["generation_run"]["provider"], "deterministic-tiny-chat")
    self.assertEqual(result["files"], [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}])
    self.assertEqual([message["role"] for message in store.chat_messages], ["user", "model"])
    self.assertIn("fast_path", store.chat_messages[0]["metadata"])
    self.assertEqual(store.chat_messages[0]["metadata"]["adaptive_route"]["route"], "tiny_chat")
    self.assertEqual(store.tool_calls, [])
    conversation = result["generation"]["multi_agent_system"]["conversation_response"]
    self.assertEqual(conversation["type"], "greeting")
    self.assertIn("build", conversation["message"].lower())

  def test_simple_code_prompt_instructs_llm_to_generate_file_not_website(self):
    routing_prompt = build_routing_prompt("write a code for reverse number in python")
    artifact_prompt = build_simple_code_prompt("write a code for reverse number in python")

    self.assertIn('intent "simple_code"', routing_prompt)
    self.assertIn('"write a code for reverse number in python" => simple_code', routing_prompt)
    self.assertIn("You are the Simple Code Writer Agent", artifact_prompt)
    self.assertIn("Generate the code\nartifact immediately", artifact_prompt)
    self.assertIn("Do not create a website, React/Vite shell", artifact_prompt)
    self.assertIn("Infer the requested programming language", artifact_prompt)
    self.assertIn("Populate generated_website.files with the code file", artifact_prompt)
    self.assertIn("Return exactly this compact JSON shape", artifact_prompt)
    self.assertNotIn("design_tokens", artifact_prompt)

  def test_simple_standalone_code_prompt_uses_model_route_and_artifact(self):
    class FakeStore:
      def __init__(self):
        self.files = [{"path": "Armstrong.java", "content": "public class Armstrong {}"}]
        self.chat_messages = []
        self.tool_calls = []
        self.agent_messages = []

      def get_project(self, project_id, user):
        return {"id": project_id, "name": "Algorithms", "description": "Browser-selected local workspace: DEMO", "local_path": None}

      def list_files(self, project_id, user):
        return list(self.files)

      def list_project_chat_messages(self, project_id, user, limit=None):
        return []

      def record_project_chat_message(self, project_id, user, *, role, content, metadata=None):
        self.chat_messages.append({"role": role, "content": content, "metadata": metadata or {}})

      def create_agent_run(self, project_id, user, **kwargs):
        return {"id": "agent-run-1", "project_id": project_id, **kwargs}

      def create_generation_run(self, project_id, user, **kwargs):
        return {"id": "generation-run-1", "project_id": project_id, **kwargs}

      def apply_generated_files(self, project_id, user, files):
        by_path = {file_item["path"]: dict(file_item) for file_item in self.files}
        for file_item in files:
          by_path[file_item["path"]] = {"path": file_item["path"], "content": file_item.get("code") or file_item.get("content") or ""}
        self.files = list(by_path.values())

      def record_agent_message(self, *args, **kwargs):
        self.agent_messages.append(kwargs)

      def record_tool_call(self, *args, **kwargs):
        self.tool_calls.append(kwargs)

      def record_generation_checkpoint(self, *args, **kwargs):
        pass

      def upsert_memory_item(self, *args, **kwargs):
        pass

      def complete_agent_run(self, agent_run_id, user, **kwargs):
        return {"id": agent_run_id, **kwargs}

    simple_code_artifact = {
      "generated_website": {
        "title": "Standalone Python Code",
        "headline": "Reverse number Program",
        "subheadline": "A plain Python file that reverses an input number.",
        "primary_cta": "Open code",
        "secondary_cta": "Run code",
        "preview_html": "",
        "theme": {
          "colors": {
            "primary": "#0f766e",
            "secondary": "#2563eb",
            "accent": "#14212b",
            "background": "#ffffff",
            "text": "#14212b",
          },
          "style_direction": "Code-only response",
        },
        "sections": [
          {
            "name": "Generated File",
            "purpose": "Record the standalone code artifact.",
            "content": "Generated reverse_number.py.",
            "items": ["reverse_number.py"],
          }
        ],
        "files": [
          {
            "path": "reverse_number.py",
            "purpose": "Standalone Python program that reverses an input number.",
            "code": (
              "def reverse_number(number: int) -> int:\n"
              "    sign = -1 if number < 0 else 1\n"
              "    return sign * int(str(abs(number))[::-1])\n\n"
              "if __name__ == \"__main__\":\n"
              "    number = int(input(\"Enter an integer: \").strip())\n"
              "    print(f\"Reverse of {number} is {reverse_number(number)}\")\n"
            ),
          }
        ],
      },
      "implementation_notes": {
        "assumptions": ["The user wants a standalone Python source file, not a website."],
        "missing_information": [],
        "predicted_risks": ["Python may not be installed locally."],
        "self_checks": ["Generated reverse_number.py"],
        "recommended_next_actions": ["Run with: python reverse_number.py"],
      },
    }

    class CapturingSimpleCodeProvider(MockProvider):
      def __init__(self):
        super().__init__(
          routing_payload={
            "intent": "simple_code",
            "next_action": "write_standalone_code_file",
            "next_tool": "generate_simple_code_file",
            "reason": "The user asked for a standalone Python code file.",
          },
          artifact_payload=simple_code_artifact,
        )
        self.calls = []

      def generate_json(self, prompt, **kwargs):
        self.calls.append(
          {
            "trace_label": kwargs.get("trace_label"),
            "prompt": prompt,
            "system_instruction": kwargs.get("system_instruction"),
            "max_output_tokens": kwargs.get("max_output_tokens"),
            "chat_history": kwargs.get("chat_history"),
            "instance_history": list(getattr(self, "chat_history", [])),
          }
        )
        return super().generate_json(prompt, **kwargs)

    provider_instance = CapturingSimpleCodeProvider()

    def simple_code_provider(*args, **kwargs):
      return provider_instance

    progress_events = []
    with patch("backend.api.generation.GeminiProvider", simple_code_provider), patch("backend.main.GeminiProvider", simple_code_provider):
      store = FakeStore()
      result = run_generation_pipeline(
        "project-1",
        "write a code for reverse number in python",
        SimpleNamespace(store=store, settings=SimpleNamespace()),
        SimpleNamespace(id="user-1"),
        progress_callback=progress_events.append,
      )

    by_path = {file_item["path"]: file_item["content"] for file_item in result["files"]}
    self.assertEqual(result["generation"]["multi_agent_system"]["intent"], "simple_code")
    self.assertEqual(result["agent_run"]["output_payload"]["intent"], "simple_code")
    self.assertIn("reverse_number.py", by_path)
    self.assertIn("def reverse_number", by_path["reverse_number.py"])
    conversation = result["generation"]["multi_agent_system"]["conversation_response"]
    self.assertEqual(conversation["type"], "simple_code")
    self.assertIn("Generated the requested standalone code file", conversation["message"])
    self.assertEqual(conversation["next_prompt_guidance"], ["Run with: python reverse_number.py"])
    progress_by_step = {event["step"]: event for event in progress_events}
    self.assertIn("agent.decision", progress_by_step)
    self.assertEqual(progress_by_step["agent.decision"]["detail"]["selected_agent"], "Simple Code Writer Agent")
    self.assertEqual(progress_by_step["agent.decision"]["detail"]["workflow"], "simple_code_model_artifact")
    self.assertEqual(progress_by_step["agent.decision"]["detail"]["existing_context_included"], False)
    self.assertEqual(progress_by_step["file.diff.ready"]["detail"]["file_count"], 1)
    self.assertEqual(progress_by_step["file.diff.ready"]["detail"]["removed"], 0)
    self.assertEqual(progress_by_step["file.diff.ready"]["detail"]["diffs"][0]["path"], "reverse_number.py")
    artifact_call = next(call for call in provider_instance.calls if call["trace_label"] == "generate_simple_code_file")
    self.assertEqual(artifact_call["chat_history"], [])
    self.assertNotIn("Armstrong.java", artifact_call["prompt"])
    self.assertNotIn("public class Armstrong", artifact_call["prompt"])
    self.assertNotIn("Core agentic operating policy", artifact_call["prompt"])
    self.assertIn("Compact code-only policy", artifact_call["prompt"])
    self.assertIn("standalone code generator", artifact_call["system_instruction"])
    self.assertNotIn("Enterprise AI-native website", artifact_call["system_instruction"])
    self.assertEqual(artifact_call["max_output_tokens"], 4096)
    self.assertEqual([message["role"] for message in store.chat_messages], ["user", "model"])

  def test_browser_selected_project_does_not_attempt_server_local_sync(self):
    class FakeStore:
      def __init__(self):
        self.files = []

      def get_project(self, project_id, user):
        return {
          "id": project_id,
          "name": "Browser CRM",
          "description": "Browser-selected local workspace: crm-app",
          "local_path": None,
        }

      def list_files(self, project_id, user):
        return list(self.files)

      def list_project_chat_messages(self, project_id, user, limit=None):
        return []

      def record_project_chat_message(self, *args, **kwargs):
        pass

      def create_agent_run(self, project_id, user, **kwargs):
        return {"id": "agent-run-1", "project_id": project_id, **kwargs}

      def create_generation_run(self, project_id, user, **kwargs):
        return {"id": "generation-run-1", "project_id": project_id, **kwargs}

      def apply_generated_files(self, project_id, user, files):
        self.files = [{"path": file["path"], "content": file.get("content") or file.get("code") or ""} for file in files]

      def record_agent_message(self, *args, **kwargs):
        pass

      def record_tool_call(self, *args, **kwargs):
        pass

      def record_generation_checkpoint(self, *args, **kwargs):
        pass

      def upsert_memory_item(self, *args, **kwargs):
        pass

      def complete_agent_run(self, agent_run_id, user, **kwargs):
        return {"id": agent_run_id, **kwargs}

    class FakeGeminiProvider:
      name = "fake-gemini"
      model = "fake-model"

      def __init__(self, *args, **kwargs):
        pass

    def fake_generate_website(*args, **kwargs):
      generation = valid_generation()
      generation["multi_agent_system"]["intent"] = "website_generation"
      generation["multi_agent_system"]["agentic_runtime"] = {}
      generation["orchestration_flow"]["generated_website"]["files"] = [
        {"path": "index.html", "content": "<div id=\"root\"></div>"},
        {"path": "src/App.jsx", "content": "export default function App() { return <main>CRM</main>; }"},
      ]
      return generation

    progress_events = []
    store = FakeStore()
    with patch("backend.main.GeminiProvider", FakeGeminiProvider), patch(
      "backend.main.generate_website",
      fake_generate_website,
    ), patch("backend.api.generation.GeminiProvider", FakeGeminiProvider), patch(
      "backend.api.generation.generate_website",
      fake_generate_website,
    ):
      result = run_generation_pipeline(
        "project-1",
        "build a crm",
        SimpleNamespace(store=store, settings=SimpleNamespace()),
        SimpleNamespace(id="user-1"),
        progress_callback=progress_events.append,
      )

    self.assertEqual([file["path"] for file in result["files"]], ["index.html", "src/App.jsx"])
    self.assertFalse([event for event in progress_events if event.get("step", "").startswith("local.sync")])

  def test_preview_runtime_converts_commonjs_configs_for_module_packages(self):
    files = prepare_preview_files(
      [
        {"path": "package.json", "content": '{"type":"module"}'},
        {"path": "postcss.config.js", "content": "module.exports = { plugins: { tailwindcss: {} } }"},
        {"path": "tailwind.config.js", "content": "module.exports = { content: ['./index.html'] }"},
      ]
    )
    by_path = {file["path"]: file["content"] for file in files}

    self.assertIn("export default", by_path["postcss.config.js"])
    self.assertIn("export default", by_path["tailwind.config.js"])
    self.assertNotIn("module.exports", by_path["postcss.config.js"])
    self.assertNotIn("module.exports", by_path["tailwind.config.js"])

  def test_preview_dependency_preflight_blocks_uninstalled_bare_import(self):
    with tempfile.TemporaryDirectory() as app_root_value:
      app_root = runtime_module.Path(app_root_value)
      for package_name in ("react", "react-dom", "lucide-react"):
        (app_root / "node_modules" / package_name).mkdir(parents=True, exist_ok=True)

      files = [
        {
          "path": "package.json",
          "content": json.dumps(
            {
              "dependencies": {
                "react": "latest",
                "react-dom": "latest",
                "react-router-dom": "latest",
              }
            }
          ),
        },
        {
          "path": "src/App.jsx",
          "content": 'import { BrowserRouter } from "react-router-dom";\nexport default function App() { return <BrowserRouter />; }',
        },
      ]

      with self.assertRaises(PreviewRuntimeError) as exc_info:
        validate_preview_dependency_imports(app_root, files)

    self.assertIn("Preview dependency preflight failed", str(exc_info.exception))
    self.assertIn("react-router-dom", str(exc_info.exception))

  def test_preview_build_runs_inside_linked_local_path(self):
    user = type("User", (), {"id": "user-1", "email": "dev@example.com", "role": "admin"})()

    with tempfile.TemporaryDirectory() as app_root_value, tempfile.TemporaryDirectory() as local_root_value:
      app_root = runtime_module.Path(app_root_value).resolve(strict=False)
      local_root = runtime_module.Path(local_root_value).resolve(strict=False)
      settings = Settings(
        database_url="postgres://example",
        frontend_origins=[],
        dev_user_email="dev@example.com",
        gemini_api_key="",
        gemini_model="gemini-test",
        app_root=app_root,
        local_workspace_roots=[local_root],
      )

      class FakeStore:
        def __init__(self):
          self.files = [
            {"path": "package.json", "content": '{"type":"module"}'},
            {"path": "index.html", "content": '<div id="root"></div><script type="module" src="/src/main.jsx"></script>'},
            {"path": "src/main.jsx", "content": "import './App.jsx';"},
            {"path": "src/App.jsx", "content": "export default function App() { return <main />; }"},
            {"path": "postcss.config.js", "content": "module.exports = { plugins: {} }"},
          ]

        def get_project(self, project_id, current_user):
          return {"id": project_id, "name": "Local project", "local_path": str(local_root)}

        def list_files(self, project_id, current_user):
          return self.files

        def create_version(self, project_id, current_user, *, version_id, status, preview_url, build_log, files):
          return {
            "id": version_id,
            "project_id": project_id,
            "status": status,
            "preview_url": preview_url,
            "build_log": build_log,
            "files": files,
          }

      original_run_vite_build = runtime_module.run_vite_build

      def fake_run_vite_build(root, workspace):
        self.assertEqual(root, app_root)
        self.assertEqual(workspace, local_root)
        self.assertTrue((local_root / "postcss.config.js").read_text(encoding="utf-8").startswith("export default"))
        (local_root / "dist").mkdir()
        (local_root / "dist" / "index.html").write_text("preview", encoding="utf-8")
        return "ok", "ready"

      try:
        runtime_module.run_vite_build = fake_run_vite_build
        version = build_project_preview(FakeStore(), "project-1", user, settings)
      finally:
        runtime_module.run_vite_build = original_run_vite_build

      self.assertEqual(version["status"], "ready")
      self.assertIn("/api/previews/project-1/", version["preview_url"])
      preview_file = app_root / ".runtime" / "projects" / "project-1" / version["id"] / "dist" / "index.html"
      self.assertEqual(preview_file.read_text(encoding="utf-8"), "preview")


if __name__ == "__main__":
  unittest.main()
