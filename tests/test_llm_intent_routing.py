from __future__ import annotations

from backend.agents.orchestration.conversation import generate_conversation_response
from backend.agents.orchestration.routing import route_generation_action_tool
from backend.agents.orchestration.state import GenerationPipelineState
from backend.agents.request_complexity import (
  ADAPTIVE_ROUTE_CONVERSATION,
  ADAPTIVE_ROUTE_ROUTING_PENDING,
  ADAPTIVE_ROUTE_TARGETED_UPDATE,
  classify_adaptive_request_route,
)


class SemanticRoutingClient:
  def __init__(self, intent: str) -> None:
    self.intent = intent
    self.calls = 0
    self.prompt = ""

  def generate_json(self, prompt: str, **_kwargs):
    self.calls += 1
    self.prompt = prompt
    return {
      "intent": self.intent,
      "reason": "The semantic router classified the user's complete speech act.",
    }


class GroundedSearchClient:
  def __init__(self) -> None:
    self.search_calls = 0
    self.normal_calls = 0

  def generate_json_with_search(self, *_args, **_kwargs):
    self.search_calls += 1
    return {
      "type": "web_search",
      "message": "Grounded search response with source links.",
      "next_prompt_guidance": ["Ask a follow-up"],
    }

  def generate_json(self, *_args, **_kwargs):
    self.normal_calls += 1
    raise AssertionError("The selected web_search tool must use the grounded provider path.")


def test_feasibility_question_is_classified_by_llm_not_python_keywords() -> None:
  client = SemanticRoutingClient("question")

  routed = route_generation_action_tool(
    "i want to change the website theme it's possible?",
    client,
  )

  assert client.calls == 1
  assert routed["intent"] == "question"
  assert routed["next_tool"] == "answer_question"


def test_same_words_can_route_to_update_when_llm_understands_command() -> None:
  client = SemanticRoutingClient("website_update")

  routed = route_generation_action_tool(
    "Can you change the website theme to red?",
    client,
  )

  assert client.calls == 1
  assert routed["intent"] == "website_update"
  assert routed["next_tool"] == "analyze_update_request"


def test_llm_router_dispatches_all_primary_chat_and_artifact_intents() -> None:
  expected_tools = {
    "question": "answer_question",
    "general_query": "answer_general_query",
    "web_search": "search_web",
    "project_info": "summarize_current_project",
    "simple_code": "generate_simple_code_file",
    "website_generation": "analyze_prompt",
    "website_update": "analyze_update_request",
  }

  for intent, expected_tool in expected_tools.items():
    client = SemanticRoutingClient(intent)
    routed = route_generation_action_tool(
      "The same natural-language input is interpreted by the model for this test.",
      client,
    )
    assert client.calls == 1
    assert routed["intent"] == intent
    assert routed["next_tool"] == expected_tool


def test_preflight_defers_intent_until_llm_route_exists() -> None:
  preflight = classify_adaptive_request_route(
    "i want to change the website theme it's possible?"
  )
  question_route = classify_adaptive_request_route(
    "i want to change the website theme it's possible?",
    intent="question",
  )
  update_route = classify_adaptive_request_route(
    "change the website theme to red",
    intent="website_update",
  )

  assert preflight.route == ADAPTIVE_ROUTE_ROUTING_PENDING
  assert question_route.route == ADAPTIVE_ROUTE_CONVERSATION
  assert update_route.route == ADAPTIVE_ROUTE_TARGETED_UPDATE


def test_llm_selected_web_search_uses_grounded_search_tool() -> None:
  client = GroundedSearchClient()
  routing_result = {
    "intent": "web_search",
    "next_action": "search_web",
    "next_tool": "search_web",
    "reason": "The LLM selected live web research.",
  }
  state = GenerationPipelineState(
    user_prompt="Find the latest React release information",
    intent="web_search",
    routing_result=routing_result,
    control_client=client,
  )

  response = generate_conversation_response(state, client)

  assert response["type"] == "web_search"
  assert client.search_calls == 1
  assert client.normal_calls == 0
