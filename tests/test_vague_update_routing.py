from __future__ import annotations

from backend.agents.orchestration.routing import route_generation_action_tool
from backend.agents.orchestration.routing_parts import (
  looks_like_underspecified_update_request,
)
from backend.agents.followup_routing import apply_existing_project_routing_bias
from backend.agents.request_understanding import assess_request_understanding


class UpdateRoutingProvider:
  def generate_json(self, prompt: str, **kwargs):
    return {
      "intent": "needs_more_detail",
      "reason": "The user has not provided a concrete target or expected change.",
      "missing_fields": ["target_page_or_component", "expected_change"],
      "clarification_question": "Which page or component should change, and what result do you want?",
    }


def test_vague_current_project_modification_requires_details() -> None:
  result = route_generation_action_tool(
    "I want to do some modification in that website",
    UpdateRoutingProvider(),
  )

  assert result["intent"] == "needs_more_detail"
  assert result["next_action"] == "request_website_details"
  assert result["next_tool"] == "request_website_details"
  assert result["request_understanding"]["clarification_required"] is True


def test_specific_update_remains_actionable() -> None:
  assert not looks_like_underspecified_update_request(
    "Modify the dashboard navbar color to blue"
  )


def test_existing_project_bias_preserves_required_clarification() -> None:
  routed = route_generation_action_tool(
    "I want to do some modification in that website",
    UpdateRoutingProvider(),
  )
  result = apply_existing_project_routing_bias(
    routed,
    prompt="I want to do some modification in that website",
    project_files=[
      {"path": "package.json", "content": "{}"},
      {"path": "index.html", "content": "<div id='root'></div>"},
      {"path": "src/App.jsx", "content": "export default function App() {}"},
    ],
  )

  assert result["intent"] == "needs_more_detail"
  assert result["request_understanding"]["clarification_required"] is True


def test_model_selected_detail_request_is_not_actionable() -> None:
  result = route_generation_action_tool(
    "change my website name",
    type(
      "DetailProvider",
      (),
      {
        "generate_json": lambda self, prompt, **kwargs: {
          "intent": "needs_more_detail",
          "reason": "The new website name is missing.",
        }
      },
    )(),
  )

  assert result["intent"] == "needs_more_detail"
  assert result["request_understanding"]["actionable"] is False
  assert result["request_understanding"]["clarification_required"] is True


def test_model_selected_detail_route_carries_missing_rename_target() -> None:
  result = route_generation_action_tool(
    "i want to change the website name",
    type(
      "RenameProvider",
      (),
      {
        "generate_json": lambda self, prompt, **kwargs: {
          "intent": "needs_more_detail",
          "reason": "The user did not provide the replacement website name.",
          "missing_fields": ["new_name_or_brand_title"],
          "clarification_question": "What exact new website name should I use?",
        }
      },
    )(),
  )

  assert result["intent"] == "needs_more_detail"
  assert result["next_tool"] == "request_website_details"
  assert result["request_understanding"]["missing_fields"] == ["new_name_or_brand_title"]


def test_missing_rename_target_requires_current_turn_confirmation() -> None:
  understanding = assess_request_understanding(
    "i want to change the website name",
    intent="website_update",
  )

  assert understanding["actionable"] is False
  assert understanding["clarification_required"] is True
  assert understanding["missing_fields"] == ["new_name_or_brand_title"]
  assert "what new name" in understanding["clarification_question"].lower()


def test_generic_feature_request_requires_specific_details() -> None:
  understanding = assess_request_understanding(
    "please add a new feature in this website",
    intent="website_update",
  )

  assert understanding["actionable"] is False
  assert understanding["clarification_required"] is True
  assert understanding["missing_fields"] == ["feature_details", "target_area"]
  assert "which feature" in understanding["clarification_question"].lower()
