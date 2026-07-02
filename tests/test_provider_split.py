from backend.llm.generator import generate_website
from backend.llm import providers as provider_module
from backend.llm.providers import (
  ARTIFACT_PROVIDER_ROLE,
  CONTROL_PROVIDER_ROLE,
  DUAL_PROVIDER_ROLE,
  GeminiProvider,
  LocalModelProvider,
  ProviderRoleError,
  is_optional_module_path_error,
)
import pytest


class RecordingProvider:
  name = "recording"

  def __init__(self, *, routing_payload=None, conversation_payload=None, artifact_payload=None, provider_role=DUAL_PROVIDER_ROLE):
    self.routing_payload = routing_payload
    self.conversation_payload = conversation_payload
    self.artifact_payload = artifact_payload
    self.provider_role = provider_role
    self.trace_labels = []
    self.prompts = []

  def generate_json(self, prompt, **kwargs):
    self.trace_labels.append(kwargs.get("trace_label"))
    self.prompts.append(prompt)
    if kwargs.get("trace_label") == "route_generation_action":
      return self.routing_payload
    if kwargs.get("trace_label") in {"handle_greeting", "request_website_details"}:
      return self.conversation_payload
    return self.artifact_payload


def artifact_payload():
  return {
    "generated_website": {
      "title": "Split Provider Site",
      "headline": "Gemini writes the code",
      "subheadline": "Local control routes the request.",
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
        }
      },
      "sections": [{"name": "Hero", "purpose": "Introduce", "content": "Hero content"}],
      "files": [{"path": "src/App.jsx", "purpose": "App", "code": "export default function App() { return <main />; }"}],
    },
    "implementation_notes": {
      "assumptions": ["Split provider test."],
      "missing_information": ["Brand assets"],
      "predicted_risks": ["Generic copy"],
      "self_checks": ["Includes src/App.jsx"],
      "recommended_next_actions": ["Build preview"],
    },
  }


def test_website_generation_uses_control_for_routing_and_artifact_for_code():
  control = RecordingProvider(
    routing_payload={
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "Control model routed to website generation.",
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "Generate an AI CRM website for B2B sales teams with pricing, demo CTA, integrations, testimonials, and dark modern style",
    control_provider=control,
    artifact_provider=artifact,
    allow_legacy_fallback=True,
  )

  assert control.trace_labels == ["route_generation_action"]
  assert artifact.trace_labels == ["generate_website_artifact"]
  assert result["gemini_tool_calling_setup"]["provider"] == "gemini-native-control-artifact"
  assert result["gemini_tool_calling_setup"]["control_provider"] == "recording"
  assert result["gemini_tool_calling_setup"]["artifact_provider"] == "recording"
  assert result["orchestration_flow"]["generated_website"]["title"] == "Split Provider Site"


def test_legacy_generation_prompt_includes_domain_research_for_ecommerce():
  control = RecordingProvider(
    routing_payload={
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "Control model routed to website generation.",
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "I don't have any specifications, just generate the e-commerce website",
    control_provider=control,
    artifact_provider=artifact,
    allow_legacy_fallback=True,
  )

  assert result["multi_agent_system"]["intent"] == "website_generation"
  assert artifact.trace_labels == ["generate_website_artifact"]
  assert '"domain": "e_commerce"' in artifact.prompts[0]
  assert "treat it as LLM-authored guidance" in artifact.prompts[0]
  assert "Never generate a monolithic src/App.jsx" in artifact.prompts[0]
  assert "src/theme/tokens.js" in artifact.prompts[0]
  assert "component_manifest" in artifact.prompts[0]
  assert "JSON-LD" in artifact.prompts[0]


def test_broad_generation_prompt_asks_for_details_before_artifact_generation():
  control = RecordingProvider(
    routing_payload={
      "intent": "needs_more_detail",
      "next_action": "request_website_details",
      "next_tool": "request_website_details",
      "reason": "The user asked for broad farm website generation.",
    },
    conversation_payload={
      "type": "needs_more_detail",
      "message": "Share the farm type, audience, sections, style, and required features.",
      "next_prompt_guidance": ["Farm type", "Audience", "Sections", "Style"],
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "Generated website for farm website with all the features",
    control_provider=control,
    artifact_provider=artifact,
  )

  assert result["multi_agent_system"]["intent"] == "needs_more_detail"
  assert result["multi_agent_system"]["routing_result"]["next_tool"] == "request_website_details"
  assert result["multi_agent_system"]["routing_result"]["reason"] == "The user asked for broad farm website generation."
  assert artifact.trace_labels == []


def test_ambiguous_generation_prompt_respects_model_selected_detail_request():
  control = RecordingProvider(
    routing_payload={
      "intent": "needs_more_detail",
      "next_action": "ask_for_more_context",
      "next_tool": "request_website_details",
      "reason": "The user did not provide a complete brief.",
    },
    conversation_payload={
      "type": "needs_more_detail",
      "message": "Share the farm type, audience, sections, style, and required features.",
      "next_prompt_guidance": ["Farm type", "Audience", "Sections", "Style"],
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "I am considering a farm web presence and need help deciding what it should include.",
    control_provider=control,
    artifact_provider=artifact,
  )

  assert result["multi_agent_system"]["intent"] == "needs_more_detail"
  assert result["multi_agent_system"]["routing_result"]["next_tool"] == "request_website_details"
  assert result["multi_agent_system"]["routing_result"]["reason"] == "The user did not provide a complete brief."
  assert artifact.trace_labels == []


def test_no_specification_generation_request_starts_with_defaults():
  control = RecordingProvider(
    routing_payload={
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "The user asked to generate with defaults.",
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "I don't have any specifications, just generate the farm website",
    control_provider=control,
    artifact_provider=artifact,
    allow_legacy_fallback=True,
  )

  assert result["multi_agent_system"]["intent"] == "website_generation"
  assert artifact.trace_labels == ["generate_website_artifact"]


def test_conversation_uses_control_provider_and_never_calls_artifact_provider():
  control = RecordingProvider(
    routing_payload={
      "intent": "greeting",
      "next_action": "respond_and_collect_website_brief",
      "next_tool": "handle_greeting",
      "reason": "Greeting only.",
    },
    conversation_payload={
      "type": "greeting",
      "message": "Hello. Tell me what website you want to build.",
      "next_prompt_guidance": ["Share website type", "Share brand name"],
    },
    provider_role=CONTROL_PROVIDER_ROLE,
  )
  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "hi",
    control_provider=control,
    artifact_provider=artifact,
  )

  assert control.trace_labels == ["route_generation_action", "handle_greeting"]
  assert artifact.trace_labels == []
  assert result["multi_agent_system"]["intent"] == "greeting"
  assert result["multi_agent_system"]["agentic_runtime"]["final_output"]["file_count"] == 0


def test_local_model_provider_supports_openai_llm_run_class_content_json():
  class FakeOpenAILLM:
    calls = []

    def __init__(self):
      self.calls = []

    def run(self, messages, tools, reasoning_effort="low"):
      call = (
        {
          "messages": messages,
          "tools": tools,
          "reasoning_effort": reasoning_effort,
        }
      )
      self.calls.append(call)
      FakeOpenAILLM.calls.append(call)
      return {
        "content": (
          '{"intent":"greeting","reason":"The user greeted the assistant."}'
        ),
        "tool_calls": None,
        "reasoning": None,
      }

  class FakeLocalModelModule:
    OpenAILLM____ = FakeOpenAILLM

  provider = LocalModelProvider(adapter=FakeLocalModelModule())

  response = provider.generate_json(
    "Route this message",
    system_instruction="Return JSON.",
    trace_label="route_generation_action",
    tools=[{"type": "function", "function": {"name": "ROUTE", "parameters": {"type": "object"}}}],
  )

  assert response == {
    "intent": "greeting",
    "reason": "The user greeted the assistant.",
  }
  assert FakeOpenAILLM.calls[-1]["tools"] == [
    {"type": "function", "function": {"name": "ROUTE", "parameters": {"type": "object"}}}
  ]


def test_local_model_provider_uses_local_model_default_name_and_fenced_json(monkeypatch):
  class FakeOpenAILLM:
    calls = []

    def __init__(self, model_name=""):
      self.model_name = model_name

    def run(self, messages, tools, reasoning_effort="low"):
      FakeOpenAILLM.calls.append({"model_name": self.model_name, "messages": messages})
      return {
        "content": '```json\n{"intent":"greeting","next_action":"respond_and_collect_website_brief"}\n```',
        "tool_calls": None,
      }

  class FakeLocalModelModule:
    DEFAULT_LOCAL_MODEL_NAME = "gpt-oss-120b"
    OpenAILLM____ = FakeOpenAILLM

  monkeypatch.delenv("LOCAL_MODEL_NAME", raising=False)
  monkeypatch.delenv("GPT_LOCAL_MODEL_NAME", raising=False)
  monkeypatch.setattr(provider_module, "import_optional_local_model", lambda: FakeLocalModelModule)

  provider = LocalModelProvider.from_env_or_module()
  response = provider.generate_json("Route this message", system_instruction="Return JSON.")

  assert provider.model == "gpt-oss-120b"
  assert FakeOpenAILLM.calls[-1]["model_name"] == "gpt-oss-120b"
  assert response["intent"] == "greeting"


def test_local_model_import_treats_missing_parent_package_as_optional_path():
  assert is_optional_module_path_error("backend.llm", "backend.llm.local_model")
  assert is_optional_module_path_error("llm.local_model", "llm.local_model")
  assert not is_optional_module_path_error("openai", "backend.llm.local_model")


def test_openai_compatible_local_model_endpoint_uses_bundled_adapter(monkeypatch):
  class FakeOpenAILLM:
    def __init__(self):
      pass

  class FakeLocalModelModule:
    OpenAILLM____ = FakeOpenAILLM

  monkeypatch.setenv("LOCAL_MODEL_ENDPOINT", "http://127.0.0.1:8003/v1")
  monkeypatch.setenv("LOCAL_MODEL_NAME", "local-control-model")
  monkeypatch.setattr(provider_module, "import_optional_local_model", lambda: FakeLocalModelModule)

  provider = LocalModelProvider.from_env_or_module()

  assert provider.adapter is FakeLocalModelModule
  assert provider.endpoint is None
  assert provider.model == "local-control-model"


def test_custom_json_local_model_endpoint_is_used_when_adapter_missing(monkeypatch):
  monkeypatch.setenv("LOCAL_MODEL_JSON_ENDPOINT", "http://127.0.0.1:9000/control-json")
  monkeypatch.setattr(provider_module, "import_optional_local_model", lambda: None)

  provider = LocalModelProvider.from_env_or_module()

  assert provider.adapter is None
  assert provider.endpoint == "http://127.0.0.1:9000/control-json"


def test_tiny_greeting_uses_deterministic_fallback_when_model_is_unavailable():
  class FailingControlProvider:
    name = "failing-local-gpt"
    provider_role = CONTROL_PROVIDER_ROLE

    def generate_json(self, prompt, **kwargs):
      raise RuntimeError("Connection error.")

  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  result = generate_website(
    "hi",
    control_provider=FailingControlProvider(),
    artifact_provider=artifact,
  )

  assert result["multi_agent_system"]["intent"] == "greeting"
  assert result["multi_agent_system"]["routing_result"]["adaptive_route"]["route"] == "tiny_chat"
  assert artifact.trace_labels == []


def test_explicit_generation_routing_failure_does_not_use_static_fallback():
  class FailingControlProvider:
    name = "failing-local-gpt"
    provider_role = CONTROL_PROVIDER_ROLE

    def generate_json(self, prompt, **kwargs):
      raise RuntimeError("Local GPT control model call failed during route_generation_action: Connection error.")

  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  with pytest.raises(Exception, match="no generation actions were started"):
    generate_website(
      "I don't have any specifications, just generate the farm website",
      control_provider=FailingControlProvider(),
      artifact_provider=artifact,
      allow_legacy_fallback=True,
    )

  assert artifact.trace_labels == []


def test_broad_generation_routing_failure_does_not_use_static_fallback():
  class FailingControlProvider:
    name = "failing-local-gpt"
    provider_role = CONTROL_PROVIDER_ROLE

    def generate_json(self, prompt, **kwargs):
      raise RuntimeError("Local GPT control model call failed during route_generation_action: Connection error.")

  artifact = RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE)

  with pytest.raises(Exception, match="no generation actions were started"):
    generate_website(
      "Generated website for farm website with all the features",
      control_provider=FailingControlProvider(),
      artifact_provider=artifact,
    )

  assert artifact.trace_labels == []


def test_artifact_provider_cannot_be_used_for_control_plane():
  artifact_only = RecordingProvider(
    routing_payload={
      "intent": "greeting",
      "next_action": "respond_and_collect_website_brief",
      "next_tool": "handle_greeting",
      "reason": "Should not be accepted as control.",
    },
    provider_role=ARTIFACT_PROVIDER_ROLE,
  )

  with pytest.raises(ProviderRoleError, match="control provider"):
    generate_website(
      "hi",
      control_provider=artifact_only,
      artifact_provider=RecordingProvider(artifact_payload=artifact_payload(), provider_role=ARTIFACT_PROVIDER_ROLE),
    )


def test_control_provider_cannot_be_used_for_artifact_plane():
  control_only = RecordingProvider(
    routing_payload={
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "Control only.",
    },
    artifact_payload=artifact_payload(),
    provider_role=CONTROL_PROVIDER_ROLE,
  )

  with pytest.raises(ProviderRoleError, match="artifact provider"):
    generate_website(
      "Generate an AI CRM website",
      control_provider=control_only,
      artifact_provider=control_only,
      allow_legacy_fallback=True,
    )


def test_project_generation_uses_gemini_for_control_and_artifact(monkeypatch):
  from backend import main as backend_main

  class FakeGeminiProvider:
    name = "gemini"
    provider_role = DUAL_PROVIDER_ROLE

    def __init__(self, *, model=None):
      self.model = model
      self.client = type("Client", (), {"model": model or "gemini-test"})()

  class FakeStore:
    def __init__(self):
      self.files = []

    def get_project(self, project_id, user):
      return {"id": project_id, "name": "Provider Split Smoke"}

    def create_agent_run(self, project_id, user, **kwargs):
      return {"id": "agent-run-1", **kwargs}

    def create_generation_run(self, project_id, user, **kwargs):
      return {"id": "generation-run-1", **kwargs}

    def complete_agent_run(self, agent_run_id, user, **kwargs):
      return {"id": agent_run_id, **kwargs}

    def list_files(self, project_id, user):
      return self.files

    def apply_generated_files(self, project_id, user, files):
      self.files = [{"path": file_item["path"], "content": file_item["code"]} for file_item in files]

  class FakeContext:
    store = FakeStore()
    settings = None

  class FakeUser:
    id = "user-1"

  def fake_generate_website(prompt, **kwargs):
    assert kwargs["control_provider"].name == "gemini"
    assert kwargs["artifact_provider"].name == "gemini"
    assert kwargs["control_provider"] is kwargs["artifact_provider"]
    return {
      "multi_agent_system": {
        "intent": "website_generation",
        "conversation_response": {"message": "Generated the website preview from the provided prompt."},
      },
      "orchestration_flow": {
        "generated_website": {
          "files": [
            {
              "path": "src/App.jsx",
              "code": "export default function App() { return <main>Provider split smoke</main>; }",
            }
          ]
        }
      },
      "gemini_tool_calling_setup": {},
      "google_adk_usage": {},
      "agent_to_agent_communication": {},
      "proactive_thinking": {},
    }

  progress_events = []
  monkeypatch.setattr(backend_main, "GeminiProvider", FakeGeminiProvider)
  monkeypatch.setattr(backend_main, "generate_website", fake_generate_website)
  monkeypatch.setattr(backend_main, "persist_agent_runtime_output", lambda *args, **kwargs: None)

  result = backend_main.run_generation_pipeline(
    "project-1",
    "Generate an AI CRM website",
    FakeContext(),
    FakeUser(),
    progress_callback=progress_events.append,
  )

  assert result["generation"]["multi_agent_system"]["intent"] == "website_generation"
  assert result["files"] == [
    {"path": "src/App.jsx", "content": "export default function App() { return <main>Provider split smoke</main>; }"}
  ]
  ready = next(event for event in progress_events if event["step"] == "provider.ready")
  assert ready["status"] == "completed"
  assert ready["message"] == "Using Gemini native control/artifact provider"
  assert not [event for event in progress_events if event["step"] == "provider.degraded"]


def test_retry_prompt_carries_previous_runtime_error_into_generation_pipeline(monkeypatch):
  from backend import main as backend_main

  class FakeGeminiProvider:
    name = "gemini"
    provider_role = DUAL_PROVIDER_ROLE

    def __init__(self, *, model=None):
      self.model = model
      self.client = type("Client", (), {"model": model or "gemini-test"})()

  class FakeStore:
    def __init__(self):
      self.files = [{"path": "src/App.jsx", "content": "export default function App() { return null; }"}]
      self.chat_messages = [
        {
          "role": "user",
          "content": "Uncaught TypeError: Cannot read properties of undefined (reading 'name') at Dashboard.jsx",
        }
      ]

    def get_project(self, project_id, user):
      return {"id": project_id, "name": "Runtime Error Project"}

    def create_agent_run(self, project_id, user, **kwargs):
      return {"id": "agent-run-1", **kwargs}

    def create_generation_run(self, project_id, user, **kwargs):
      return {"id": "generation-run-1", **kwargs}

    def complete_agent_run(self, agent_run_id, user, **kwargs):
      return {"id": agent_run_id, **kwargs}

    def list_files(self, project_id, user):
      return list(self.files)

    def list_project_chat_messages(self, project_id, user, limit=None):
      return list(self.chat_messages)

    def record_project_chat_message(self, project_id, user, *, role, content, metadata=None):
      self.chat_messages.append({"role": role, "content": content, "metadata": metadata or {}})

    def apply_generated_files(self, project_id, user, files):
      self.files = [{"path": file_item["path"], "content": file_item["code"]} for file_item in files]

  class FakeContext:
    def __init__(self):
      self.store = FakeStore()
      self.settings = object()

  class FakeUser:
    id = "user-1"

  captured = {}

  def fake_generate_website(prompt, **kwargs):
    captured["prompt"] = prompt
    return {
      "multi_agent_system": {
        "intent": "website_update",
        "conversation_response": {"message": "Updated."},
        "agentic_runtime": {"tool_source_of_truth": False},
      },
      "orchestration_flow": {
        "generated_website": {
          "files": [
            {
              "path": "src/App.jsx",
              "code": "export default function App() { return <main>fixed</main>; }",
            }
          ]
        }
      },
      "gemini_tool_calling_setup": {},
      "google_adk_usage": {},
      "agent_to_agent_communication": {},
      "proactive_thinking": {},
    }

  monkeypatch.setattr(backend_main, "GeminiProvider", FakeGeminiProvider)
  monkeypatch.setattr(backend_main, "generate_website", fake_generate_website)
  monkeypatch.setattr(backend_main, "persist_agent_runtime_output", lambda *args, **kwargs: None)

  result = backend_main.run_generation_pipeline(
    "project-1",
    "try again",
    FakeContext(),
    FakeUser(),
  )

  assert result["generation"]["multi_agent_system"]["intent"] == "website_update"
  assert "Additional conversation context for model routing and planning" in captured["prompt"]
  assert "Previous runtime/build error context available to the Chief Orchestrator:" in captured["prompt"]
  assert "Cannot read properties of undefined" in captured["prompt"]
  assert "Route through the error handling path first" not in captured["prompt"]


def test_tool_source_generation_fallback_syncs_linked_local_folder(monkeypatch):
  from backend import main as backend_main
  from backend.api import generation as generation_api

  class FakeGeminiProvider:
    name = "gemini"
    provider_role = DUAL_PROVIDER_ROLE

    def __init__(self, *, model=None):
      self.model = model
      self.client = type("Client", (), {"model": model or "gemini-test"})()

  class FakeStore:
    def __init__(self):
      self.files = [{"path": "src/App.jsx", "content": "old"}]

    def get_project(self, project_id, user):
      return {"id": project_id, "name": "Linked Project", "local_path": "/tmp/worktual-linked-project"}

    def create_agent_run(self, project_id, user, **kwargs):
      return {"id": "agent-run-1", **kwargs}

    def create_generation_run(self, project_id, user, **kwargs):
      return {"id": "generation-run-1", **kwargs}

    def complete_agent_run(self, agent_run_id, user, **kwargs):
      return {"id": agent_run_id, **kwargs}

    def list_files(self, project_id, user):
      return list(self.files)

  class FakeContext:
    def __init__(self):
      self.store = FakeStore()
      self.settings = object()

  class FakeUser:
    id = "user-1"

  generated_files = [{"path": "src/App.jsx", "content": "new"}]

  def fake_generate_website(prompt, **kwargs):
    return {
      "multi_agent_system": {
        "intent": "website_update",
        "conversation_response": {"message": "Updated."},
        "agentic_runtime": {"tool_source_of_truth": True, "local_sync": None},
      },
      "orchestration_flow": {"generated_website": {"files": generated_files}},
      "gemini_tool_calling_setup": {},
      "google_adk_usage": {},
      "agent_to_agent_communication": {},
      "proactive_thinking": {},
    }

  synced = {}

  def fake_write_linked_project_files(context, project, files, user, *, event_type, prune_missing=False):
    synced["project"] = project
    synced["files"] = files
    synced["event_type"] = event_type
    synced["prune_missing"] = prune_missing
    return {"path": project["local_path"], "count": len(files)}

  monkeypatch.setattr(backend_main, "GeminiProvider", FakeGeminiProvider)
  monkeypatch.setattr(backend_main, "generate_website", fake_generate_website)
  monkeypatch.setattr(backend_main, "persist_agent_runtime_output", lambda *args, **kwargs: None)
  monkeypatch.setattr(generation_api, "write_linked_project_files", fake_write_linked_project_files)

  result = backend_main.run_generation_pipeline(
    "project-1",
    "Fix the imported website",
    FakeContext(),
    FakeUser(),
  )

  assert synced["files"] == generated_files
  assert synced["event_type"] == "local.files.written"
  assert synced["prune_missing"] is False
  assert result["local_sync"] == {"path": "/tmp/worktual-linked-project", "count": 1}


def test_non_tool_generation_syncs_linked_local_folder_before_project_store(monkeypatch):
  from backend import main as backend_main
  from backend.api import generation as generation_api

  class FakeGeminiProvider:
    name = "gemini"
    provider_role = DUAL_PROVIDER_ROLE

    def __init__(self, *, model=None):
      self.model = model
      self.client = type("Client", (), {"model": model or "gemini-test"})()

  class FakeStore:
    def __init__(self):
      self.local_was_synced = False
      self.applied_files = None

    def get_project(self, project_id, user):
      return {"id": project_id, "name": "Linked Project", "local_path": "/tmp/worktual-linked-project"}

    def create_agent_run(self, project_id, user, **kwargs):
      return {"id": "agent-run-1", **kwargs}

    def create_generation_run(self, project_id, user, **kwargs):
      return {"id": "generation-run-1", **kwargs}

    def complete_agent_run(self, agent_run_id, user, **kwargs):
      return {"id": agent_run_id, **kwargs}

    def list_files(self, project_id, user):
      return []

    def apply_generated_files(self, project_id, user, files):
      assert self.local_was_synced is True
      self.applied_files = files

  class FakeContext:
    def __init__(self):
      self.store = FakeStore()
      self.settings = object()

  class FakeUser:
    id = "user-1"

  generated_files = [{"path": "src/pages/Dashboard.jsx", "code": "line\n" * 409}]

  def fake_generate_website(prompt, **kwargs):
    return {
      "multi_agent_system": {
        "intent": "website_update",
        "conversation_response": {"message": "Updated."},
        "agentic_runtime": {"tool_source_of_truth": False},
      },
      "orchestration_flow": {"generated_website": {"files": generated_files}},
      "gemini_tool_calling_setup": {},
      "google_adk_usage": {},
      "agent_to_agent_communication": {},
      "proactive_thinking": {},
    }

  context = FakeContext()

  def fake_write_linked_project_files(context_arg, project, files, user, *, event_type, prune_missing=False):
    assert files == generated_files
    context.store.local_was_synced = True
    return {"path": project["local_path"], "count": len(files)}

  monkeypatch.setattr(backend_main, "GeminiProvider", FakeGeminiProvider)
  monkeypatch.setattr(backend_main, "generate_website", fake_generate_website)
  monkeypatch.setattr(backend_main, "persist_agent_runtime_output", lambda *args, **kwargs: None)
  monkeypatch.setattr(generation_api, "write_linked_project_files", fake_write_linked_project_files)

  result = backend_main.run_generation_pipeline(
    "project-1",
    "Update dashboard",
    context,
    FakeUser(),
  )

  assert context.store.applied_files == generated_files
  assert result["local_sync"] == {"path": "/tmp/worktual-linked-project", "count": 1}


def test_save_file_syncs_linked_local_folder_before_project_store(monkeypatch):
  from backend import main as backend_main

  class FakeStore:
    def __init__(self):
      self.local_was_synced = False
      self.saved_file = None

    def get_project(self, project_id, user):
      return {"id": project_id, "name": "Linked Project", "local_path": "/tmp/worktual-linked-project"}

    def upsert_file(self, project_id, user, *, path, content):
      assert self.local_was_synced is True
      self.saved_file = {"path": path, "content": content}
      return self.saved_file

  class FakeContext:
    def __init__(self):
      self.store = FakeStore()
      self.settings = object()

  class FakeUser:
    id = "user-1"

  context = FakeContext()

  def fake_write_linked_project_files(context_arg, project, files, user, *, event_type, prune_missing=False):
    assert files == [{"path": "src/pages/Dashboard.jsx", "content": "updated dashboard"}]
    context.store.local_was_synced = True
    return {"path": project["local_path"], "count": len(files)}

  monkeypatch.setattr(backend_main, "write_linked_project_files", fake_write_linked_project_files)

  result = backend_main.save_file(
    "project-1",
    "src/pages/Dashboard.jsx",
    backend_main.SaveFileRequest(content="updated dashboard"),
    context,
    FakeUser(),
  )

  assert result["file"] == {"path": "src/pages/Dashboard.jsx", "content": "updated dashboard"}
  assert result["local_sync"] == {"path": "/tmp/worktual-linked-project", "count": 1}


def test_gemini_provider_is_dual_role():
  provider = GeminiProvider(client=type("Client", (), {"model": "gemini-test"})())

  from backend.llm.providers import assert_provider_role

  assert_provider_role(provider, CONTROL_PROVIDER_ROLE)
  assert_provider_role(provider, ARTIFACT_PROVIDER_ROLE)
