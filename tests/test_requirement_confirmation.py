from __future__ import annotations

import json

from backend.agent_tools import ToolRuntimeContext
from backend.llm.agentic_evals import evaluate_agentic_response
from backend.llm.generator import generate_website
from backend.llm import orchestrator as orchestrator_module
from backend.llm.providers import DUAL_PROVIDER_ROLE
from backend.agents.orchestration import runner as runner_module
from backend.agents.request_complexity import classify_adaptive_request_route
from backend.llm.requirement_confirmation import (
  confirmed_routing_result,
  evaluate_confirmation_reply,
  load_pending_confirmation,
  load_retryable_confirmation,
  normalize_confirmation_brief,
  prepare_confirmation_brief,
)


class ConfirmationSettings:
  require_plan_confirmation = True


class ConfirmationStore:
  def __init__(self):
    self.memories = []

  def list_memory_items(self, user, *, project_id=None, namespace=None, limit=12):
    items = [
      item
      for item in reversed(self.memories)
      if (project_id is None or item["project_id"] == project_id)
      and (namespace is None or item["namespace"] == namespace)
    ]
    return items[:limit]

  def upsert_memory_item(self, user, *, project_id, namespace, key, kind, content, metadata=None):
    self.memories = [
      item
      for item in self.memories
      if not (item["project_id"] == project_id and item["namespace"] == namespace and item["key"] == key)
    ]
    item = {
      "project_id": project_id,
      "namespace": namespace,
      "key": key,
      "kind": kind,
      "content": content,
      "metadata_json": metadata or {},
    }
    self.memories.append(item)
    return item


class ConfirmationProvider:
  name = "gemini"
  provider_role = DUAL_PROVIDER_ROLE

  def __init__(self, *, route_intent="website_generation", confirmation_required=True, decision="confirm"):
    self.route_intent = route_intent
    self.confirmation_required = confirmation_required
    self.decision = decision
    self.trace_labels = []

  def generate_json(self, prompt, **kwargs):
    label = kwargs.get("trace_label")
    self.trace_labels.append(label)
    if label == "route_generation_action":
      if self.route_intent == "simple_code":
        return {
          "intent": "simple_code",
          "next_action": "write_standalone_code_file",
          "next_tool": "generate_simple_code_file",
          "reason": "The model selected standalone code generation.",
        }
      if self.route_intent == "website_update":
        return {
          "intent": "website_update",
          "next_action": "update_website",
          "next_tool": "analyze_update_request",
          "reason": "The model selected an existing website update.",
        }
      return {
        "intent": "website_generation",
        "next_action": "generate_website",
        "next_tool": "analyze_prompt",
        "reason": "The model selected website generation.",
      }
    if label == "prepare_requirement_confirmation":
      return {
        "confirmation_required": self.confirmation_required,
        "risk_level": "high" if self.route_intent == "website_generation" else "low",
        "summary": "Build a complete e-commerce storefront.",
        "planned_changes": ["Create the storefront.", "Validate and preview it."],
        "assumptions": ["Use realistic starter products."],
        "open_questions": [],
        "scope_boundaries": ["Preserve unrelated existing code."],
        "reason": "Confirm high-impact work before execution.",
      }
    if label == "evaluate_requirement_confirmation":
      return {
        "decision": self.decision,
        "revision": "Use a red visual theme." if self.decision == "revise" else "",
        "reason": "Classified the user response.",
      }
    raise AssertionError(f"Unexpected model call: {label}")


class SimpleCodeConfirmationProvider(ConfirmationProvider):
  def __init__(self):
    super().__init__(route_intent="simple_code")

  def generate_json(self, prompt, **kwargs):
    label = kwargs.get("trace_label")
    if label == "generate_simple_code_file":
      self.trace_labels.append(label)
      return {
        "generated_website": {
          "title": "Standalone Python Code",
          "headline": "Armstrong Number",
          "subheadline": "A standalone Python Armstrong number program.",
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
              "content": "Generated armstrong_number.py.",
              "items": ["armstrong_number.py"],
            }
          ],
          "files": [
            {
              "path": "armstrong_number.py",
              "purpose": "Standalone Armstrong number program.",
              "code": "def is_armstrong_number(number: int) -> bool:\n    return True\n",
            }
          ],
        },
        "implementation_notes": {
          "recommended_next_actions": ["Run with: python armstrong_number.py"],
          "self_checks": ["Generated one standalone file."],
        },
      }
    return super().generate_json(prompt, **kwargs)


class User:
  id = "user-1"
  role = "admin"


def confirmation_context():
  store = ConfirmationStore()
  return ToolRuntimeContext(store=store, settings=ConfirmationSettings()), store


def runtime_result():
  generated_website = {
    "title": "Confirmed Site",
    "headline": "Confirmed",
    "subheadline": "Generated after approval.",
    "primary_cta": "Start",
    "secondary_cta": "Learn",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#111111",
        "secondary": "#222222",
        "accent": "#333333",
        "background": "#ffffff",
        "text": "#111111",
      },
      "style_direction": "Clean",
    },
    "sections": [{"name": "Hero", "purpose": "Introduce", "content": "Confirmed content", "items": ["One"]}],
    "files": [{"path": "src/App.jsx", "purpose": "App", "code": "export default function App(){return <main />;}"}],
  }
  return {
    "generated_website": generated_website,
    "artifact_response": {"generated_website": generated_website, "implementation_notes": {}},
    "runtime": {
      "tool_source_of_truth": True,
      "branch": "website_generation",
      "operation": "generate",
      "tool_calls": [],
      "steps": [],
      "handoffs": [],
      "agents": [],
      "completion_status": {"status": "completed"},
      "completion_proof": {},
      "final_output": {"file_count": 1},
    },
  }


def test_generation_prepares_persisted_execution_brief_before_artifact_work():
  context, store = confirmation_context()
  provider = ConfirmationProvider(route_intent="website_generation")

  result = generate_website(
    "Generate an e-commerce website with catalog, cart, and checkout",
    control_provider=provider,
    artifact_provider=provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert result["multi_agent_system"]["intent"] == "needs_confirmation"
  assert result["gemini_tool_calling_setup"]["tool_call_sequence"] == [
    "route_generation_action",
    "confirm_execution_brief",
  ]
  assert result["multi_agent_system"]["conversation_response"]["confirmation"]["status"] == "pending"
  assert provider.trace_labels == ["route_generation_action", "prepare_requirement_confirmation"]
  pending = load_pending_confirmation(context, User(), project_id="project-1")
  assert pending["operation"] == "website_generation"
  assert pending["summary"] == "Build a complete e-commerce storefront."
  assert store.memories
  assert evaluate_agentic_response(result)["passed"] is True


def test_confirmed_brief_remains_retryable_until_execution_completes():
  context, store = confirmation_context()
  provider = ConfirmationProvider(route_intent="website_generation")
  generate_website(
    "Generate an e-commerce website with catalog, cart, and checkout",
    control_provider=provider,
    artifact_provider=provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  pending = load_pending_confirmation(context, User(), project_id="project-1")
  pending["status"] = "confirmed"
  store.upsert_memory_item(
    User(),
    project_id="project-1",
    namespace="confirmation",
    key="pending_execution_brief",
    kind="execution_brief",
    content=json.dumps(pending),
    metadata={"status": "confirmed"},
  )

  assert load_pending_confirmation(context, User(), project_id="project-1") is None
  assert load_retryable_confirmation(context, User(), project_id="project-1")["status"] == "confirmed"


def test_pending_confirmation_can_be_cancelled_without_artifact_generation():
  context, _ = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_generation")
  generate_website(
    "Generate an e-commerce website",
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  cancel_provider = ConfirmationProvider(decision="cancel")

  result = generate_website(
    "Cancel it",
    control_provider=cancel_provider,
    artifact_provider=cancel_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert result["multi_agent_system"]["intent"] == "needs_confirmation"
  assert result["multi_agent_system"]["conversation_response"]["message"].startswith("Cancelled")
  assert cancel_provider.trace_labels == []
  assert load_pending_confirmation(context, User(), project_id="project-1") is None


def test_pending_confirmation_simple_code_request_supersedes_brief():
  context, store = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_generation")
  generate_website(
    "Generate an e-commerce website",
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  simple_provider = SimpleCodeConfirmationProvider()

  result = generate_website(
    "write a code for armstrong number in python",
    control_provider=simple_provider,
    artifact_provider=simple_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert result["multi_agent_system"]["intent"] == "simple_code"
  assert result["orchestration_flow"]["generated_website"]["files"][0]["path"] == "armstrong_number.py"
  assert simple_provider.trace_labels == ["route_generation_action", "generate_simple_code_file"]
  assert load_pending_confirmation(context, User(), project_id="project-1") is None
  assert any(item["metadata_json"].get("status") == "superseded" for item in store.memories)


def test_confirmed_brief_resumes_original_request(monkeypatch):
  context, _ = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_generation")
  original_request = "Generate an e-commerce website with catalog and checkout"
  generate_website(
    original_request,
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  captured = {}

  def fake_runtime(**kwargs):
    captured.update(kwargs)
    return runtime_result()

  monkeypatch.setattr(orchestrator_module, "execute_real_agent_runtime_loop", fake_runtime)
  confirm_provider = ConfirmationProvider(decision="confirm")

  result = generate_website(
    "Confirm and proceed",
    control_provider=confirm_provider,
    artifact_provider=confirm_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert captured["prompt"] == original_request
  assert result["multi_agent_system"]["intent"] == "website_generation"
  assert confirm_provider.trace_labels == []
  assert load_pending_confirmation(context, User(), project_id="project-1") is None


def test_confirmed_brief_reclassifies_original_request_for_parallel_generation(monkeypatch):
  context, _ = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_generation")
  original_request = "Generate an e-commerce website with catalog, cart, checkout, reports, and settings"
  generate_website(
    original_request,
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  captured = {}

  def fake_parallel_runtime(**kwargs):
    captured.update(kwargs)
    return runtime_result()

  monkeypatch.setattr(runner_module, "run_parallel_stream_orchestrator", fake_parallel_runtime)
  context.store.list_files = lambda *_args, **_kwargs: []
  confirm_provider = ConfirmationProvider(decision="confirm")
  stale_confirmation_route = classify_adaptive_request_route(
    "Confirm and proceed with this execution brief."
  ).to_dict()

  result = generate_website(
    "Confirm and proceed with this execution brief.",
    control_provider=confirm_provider,
    artifact_provider=confirm_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
    confirmation_action="confirm",
    adaptive_route=stale_confirmation_route,
  )

  adaptive_route = result["multi_agent_system"]["routing_result"]["adaptive_route"]
  assert captured["prompt"] == original_request
  assert adaptive_route["route"] == "full_generation"
  assert adaptive_route["reclassified_after_confirmation"] is True


def test_new_request_during_pending_confirmation_routes_only_once():
  context, _ = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_generation")
  generate_website(
    "Generate an e-commerce website",
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  next_provider = ConfirmationProvider(route_intent="website_generation")

  result = generate_website(
    "Generate a CRM website with reports and settings",
    control_provider=next_provider,
    artifact_provider=next_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert result["multi_agent_system"]["intent"] == "needs_confirmation"
  assert next_provider.trace_labels == ["route_generation_action", "prepare_requirement_confirmation"]


def test_explicit_confirm_action_resumes_pending_brief(monkeypatch):
  context, _ = confirmation_context()
  first_provider = ConfirmationProvider(route_intent="website_update")
  original_request = "Update the LangGraph RAG bot prompt template"
  generate_website(
    original_request,
    control_provider=first_provider,
    artifact_provider=first_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )
  captured = {}

  def fake_runtime(**kwargs):
    captured.update(kwargs)
    return runtime_result()

  monkeypatch.setattr(orchestrator_module, "execute_real_agent_runtime_loop", fake_runtime)
  confirm_provider = ConfirmationProvider(decision="unclear")

  result = generate_website(
    "Confirm and proceed with this execution brief.",
    control_provider=confirm_provider,
    artifact_provider=confirm_provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
    confirmation_action="confirm",
  )

  assert captured["prompt"] == original_request
  assert result["multi_agent_system"]["intent"] == "website_update"
  assert load_pending_confirmation(context, User(), project_id="project-1") is None


def test_low_risk_update_bypasses_confirmation_and_runs_scoped_runtime(monkeypatch):
  context, _ = confirmation_context()
  captured = {}

  def fake_runtime(**kwargs):
    captured.update(kwargs)
    result = runtime_result()
    result["runtime"]["branch"] = "website_update"
    result["runtime"]["operation"] = "update"
    return result

  monkeypatch.setattr(orchestrator_module, "execute_real_agent_runtime_loop", fake_runtime)
  provider = ConfirmationProvider(route_intent="website_update", confirmation_required=False)
  update_request = "Change the primary button color to red"

  result = generate_website(
    update_request,
    control_provider=provider,
    artifact_provider=provider,
    project_id="project-1",
    tool_context=context,
    user=User(),
  )

  assert captured["prompt"] == update_request
  assert result["multi_agent_system"]["intent"] == "website_update"
  assert provider.trace_labels == ["route_generation_action", "prepare_requirement_confirmation"]
  assert load_pending_confirmation(context, User(), project_id="project-1") is None


def test_update_confirmation_model_can_allow_low_risk_scoped_patch():
  provider = ConfirmationProvider(route_intent="website_update", confirmation_required=False)

  brief = prepare_confirmation_brief(provider, "Change the primary button color to red", operation="website_update")

  assert brief["confirmation_required"] is False
  assert brief["risk_level"] == "low"


def test_generation_confirmation_cannot_be_disabled_by_model_output():
  brief = normalize_confirmation_brief(
    {
      "confirmation_required": False,
      "risk_level": "low",
      "summary": "Generate a site.",
      "planned_changes": ["Generate it."],
    },
    user_prompt="Generate a site",
    operation="website_generation",
  )

  assert brief["confirmation_required"] is True


def test_confirmation_decision_and_confirmed_route_are_model_driven():
  provider = ConfirmationProvider(decision="confirm")
  pending = {
    "operation": "website_update",
    "summary": "Add pagination.",
    "planned_changes": ["Patch the catalog."],
  }

  decision = evaluate_confirmation_reply(provider, "Confirm and proceed", pending)
  route = confirmed_routing_result(pending)

  assert decision["decision"] == "confirm"
  assert route["intent"] == "website_update"
  assert route["next_tool"] == "analyze_update_request"
