from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_simple_greeting_prompt_uses_fast_path_detector():
    from api.generation import is_simple_greeting_prompt

    assert is_simple_greeting_prompt("hi")
    assert is_simple_greeting_prompt("Hello!")
    assert is_simple_greeting_prompt("good morning")
    assert not is_simple_greeting_prompt("hi create a website for my shop")


def test_fast_greeting_generation_matches_frontend_contract():
    from api.generation import build_fast_greeting_generation

    class FakeGreetingModel:
        def generate_json(self, prompt, **kwargs):
            return {
                "message": "Hey, welcome back to Worktual.\nI can help shape your next website idea.\nTell me the business, audience, and style you want.",
                "next_prompt_guidance": ["Business name", "Target audience", "Pages", "Style"],
            }

    generation = build_fast_greeting_generation("hi", model_provider=FakeGreetingModel())
    multi_agent = generation["multi_agent_system"]
    conversation = multi_agent["conversation_response"]

    assert multi_agent["intent"] == "greeting"
    assert conversation["message"]
    assert len(conversation["message"].splitlines()) == 3
    assert "welcome back" in conversation["message"]
    assert "website" in conversation["message"].lower()
    assert conversation["next_prompt_guidance"]
    assert generation["orchestration_flow"]["generated_website"]["files"][0]["path"] == "conversation/response.json"


def test_greeting_fallback_is_prompt_aware_not_static():
    from agents.orchestration.conversation import deterministic_conversation_response
    from agents.orchestration.state import GenerationPipelineState

    response = deterministic_conversation_response(
        GenerationPipelineState(user_prompt="hello team", intent="greeting", routing_result={}),
        error="model unavailable",
    )

    assert "hello team" in response["message"].lower()
    assert "Share the website or app you want to build" not in response["message"]
    assert "website" in response["message"].lower() or "app" in response["message"].lower()
