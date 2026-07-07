from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agents.schema import ResponseContractError
from backend.agents.orchestration.runner_parts.core_parts import routing as routing_module


class _MissingGeminiKeyProvider:
  def generate_json(self, *_args, **_kwargs):
    raise RuntimeError("Missing GEMINI_API_KEY in .env")


class _Store:
  def list_files(self, *_args, **_kwargs):
    return [
      {"path": "src/App.jsx", "content": "export default function App(){ return null; }"},
      {"path": "src/pages/Deals.jsx", "content": "export default function Deals(){ return <button type='button'>Create Action Plan</button>; }"},
    ]

  def list_project_chat_messages(self, *_args, **_kwargs):
    return []


def _orchestrator() -> tuple[SimpleNamespace, list[dict]]:
  events: list[dict] = []
  orchestrator = SimpleNamespace(
    project_id="project-1",
    tool_context=SimpleNamespace(store=_Store(), settings=SimpleNamespace(require_plan_confirmation=False)),
    user=SimpleNamespace(id="user-1"),
    attachments=[],
    adaptive_route={},
    chat_session_id="chat-1",
    chat_topic_id=None,
    initial_execution_prompt="",
    _emit_progress=lambda step, message, **kwargs: events.append(
      {"step": step, "message": message, **kwargs}
    ),
  )
  return orchestrator, events


def test_missing_gemini_key_routes_existing_project_update_on_first_attempt(monkeypatch) -> None:
  monkeypatch.setattr(routing_module, "is_vite_scaffold_complete", lambda _files: True)
  monkeypatch.setattr(
    routing_module,
    "route_generation_action_tool",
    lambda *_args, **_kwargs: (_ for _ in ()).throw(ResponseContractError("Missing GEMINI_API_KEY in .env")),
  )

  orchestrator, events = _orchestrator()

  result = routing_module.build_routing_context(
    orchestrator,
    (
      "in Manage Your Deals & Opportunities page remove the create action plan "
      "popup and add it as a modal"
    ),
    confirmation_action=None,
    control_client=_MissingGeminiKeyProvider(),
    artifact_client=object(),
  )

  routing_result = result["routing_result"]
  assert routing_result["intent"] == "website_update"
  assert routing_result["next_tool"] == "analyze_update_request"
  assert routing_result["decision_source"] == "existing_project_update_fallback"
  assert routing_result["orchestrator_brain"]["query_policy"]["query_class"] == "website_update"
  assert "codex" in routing_result["orchestrator_brain"]["agentic_platform_knowledge"]
  assert "interaction_contract_reasoning" in routing_result["orchestrator_brain"]["selected_capabilities"]
  assert any(event["step"] == "routing.model_unavailable_fallback" for event in events)
  assert any(event["step"] == "orchestrator.brain.ready" for event in events)


def test_missing_gemini_key_does_not_guess_non_update_prompt(monkeypatch) -> None:
  monkeypatch.setattr(routing_module, "is_vite_scaffold_complete", lambda _files: True)

  orchestrator, _events = _orchestrator()

  with pytest.raises(Exception, match="no generation actions were started"):
    routing_module.build_routing_context(
      orchestrator,
      "hi",
      confirmation_action=None,
      control_client=_MissingGeminiKeyProvider(),
      artifact_client=object(),
    )


class _ReferentialRoutingProvider:
  def __init__(self) -> None:
    self.last_prompt = ""

  def generate_json(self, prompt: str, **_kwargs):
    self.last_prompt = prompt
    return {
      "intent": "website_update" if "create action button is not working in deals page" in prompt.lower() and "button: create action plan" in prompt.lower() else "needs_more_detail",
      "reason": "Used same-topic continuity for routing." if "create action button is not working in deals page" in prompt.lower() and "button: create action plan" in prompt.lower() else "Prompt is still ambiguous.",
      "missing_fields": [] if "create action button is not working in deals page" in prompt.lower() and "button: create action plan" in prompt.lower() else ["button_identifier"],
      "clarification_question": "" if "create action button is not working in deals page" in prompt.lower() and "button: create action plan" in prompt.lower() else "Which button is it?",
    }


def test_routing_uses_same_topic_followup_context_before_llm_intent_decision(monkeypatch) -> None:
  monkeypatch.setattr(routing_module, "is_vite_scaffold_complete", lambda _files: True)

  class _ChatStore(_Store):
    def list_project_chat_messages(self, *_args, **_kwargs):
      return [
        {"role": "user", "content": "In deals page one button is not working"},
        {"role": "model", "content": "Which specific button is not working, and what should happen when you click it?"},
        {"role": "user", "content": "create action button is not working in deals page"},
        {"role": "model", "content": "Okay, I understand this is the create action button on the Deals page."},
      ]

  events: list[dict] = []
  orchestrator = SimpleNamespace(
    project_id="project-1",
    tool_context=SimpleNamespace(store=_ChatStore(), settings=SimpleNamespace(require_plan_confirmation=False)),
    user=SimpleNamespace(id="user-1"),
    attachments=[],
    adaptive_route={},
    chat_session_id="chat-1",
    chat_topic_id="topic-1",
    initial_execution_prompt="",
    _emit_progress=lambda step, message, **kwargs: events.append({"step": step, "message": message, **kwargs}),
  )
  provider = _ReferentialRoutingProvider()

  result = routing_module.build_routing_context(
    orchestrator,
    "while click that button there is no action is hapeening",
    confirmation_action=None,
    control_client=provider,
    artifact_client=object(),
  )

  assert result["routing_result"]["intent"] == "website_update"
  assert "create action button is not working in deals page" in provider.last_prompt.lower()
  assert any(event["step"] == "routing.same_topic_continuity" for event in events)
  assert any(event["step"] == "routing.resolved_target_context" for event in events)
  assert any(event["step"] == "routing.interaction_followup_resolved" for event in events)
