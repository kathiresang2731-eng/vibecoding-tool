from __future__ import annotations

from backend.agents.orchestration.conversation_parts.response import generate_conversation_response
from backend.agents.orchestration.state import GenerationPipelineState
from backend.agents.project_inspection import (
  build_project_inspection_context,
  build_target_resolution,
  clarification_for_ambiguous_update_target,
)


PROJECT_FILES = [
  {
    "path": "src/pages/Operations.jsx",
    "content": """
      export default function Operations() {
        return (
          <main>
            <h1>Operation Hub</h1>
            <button type="button">Run Audit</button>
            <button type="button" aria-label="Refresh operation hub"></button>
          </main>
        );
      }
    """,
  },
  {
    "path": "src/pages/Deals.jsx",
    "content": """
      export default function Deals() {
        return <button type="button">Create Action Plan</button>;
      }
    """,
  },
]


def test_button_label_extraction_ignores_jsx_arrow_function_attributes() -> None:
  context = build_project_inspection_context(
    [
      {
        "path": "src/pages/Dashboard.jsx",
        "content": """
          export default function Dashboard() {
            return (
              <main>
                <button
                  onClick={() => navigate('/contacts')}
                  className="bg-neutral-900 text-white"
                >
                  <span>Contacts Directory</span>
                </button>
                <button
                  onClick={() => setShowMessage(null)}
                  title="Dismiss action"
                  className="rounded-full"
                >
                  <X />
                </button>
              </main>
            );
          }
        """,
      },
    ],
    question="how many buttons are there in dashboard page",
  )

  facts = context["selected_live_files"][0]["button_facts"]
  assert facts["button_count"] == 2
  assert facts["labels"] == ["Contacts Directory", "Dismiss action"]
  assert all("className" not in label and "navigate" not in label for label in facts["labels"])


def test_project_info_contextual_page_reference_resolves_to_recent_page() -> None:
  context = build_project_inspection_context(
    PROJECT_FILES,
    question="what are the buttons are there in that page total count",
    chat_messages=[
      {"role": "user", "content": "now explain about the operation hub page"},
      {"role": "assistant", "content": "The Operations page (`src/pages/Operations.jsx`) is the operation hub."},
    ],
  )

  assert context["resolved_reference"]["path"] == "src/pages/Operations.jsx"
  assert context["resolved_reference"]["source"] == "chat_history"
  assert context["target_resolution"]["resolved_page"] == "Operations"
  assert context["target_resolution"]["resolved_route"] == "/operations"
  assert context["target_resolution"]["resolved_files"] == ["src/pages/Operations.jsx"]
  assert context["target_resolution"]["resolved_button"] == ""
  assert context["target_resolution"]["source"] == "chat_history"
  assert context["selected_live_files"][0]["path"] == "src/pages/Operations.jsx"
  assert context["selected_live_files"][0]["button_facts"] == {
    "button_count": 2,
    "labels": ["Run Audit", "Refresh operation hub"],
  }


def test_target_resolution_recovers_that_button_from_recent_chat() -> None:
  target = build_target_resolution(
    "make that button open as a modal instead of popup",
    PROJECT_FILES,
    chat_messages=[
      {"role": "user", "content": "in Manage Your Deals page Create Action Plan button shows a popup"},
      {"role": "assistant", "content": "The Deals page (`src/pages/Deals.jsx`) owns the Create Action Plan button."},
    ],
  )

  assert target["status"] == "resolved"
  assert target["resolved_page"] == "Deals"
  assert target["resolved_route"] == "/deals"
  assert target["resolved_files"] == ["src/pages/Deals.jsx"]
  assert target["resolved_button"] == "Create Action Plan"
  assert target["confidence"] >= 0.8
  assert "chat_history" in target["source"]


def test_ambiguous_button_issue_requires_clarification_when_page_has_multiple_buttons() -> None:
  clarification = clarification_for_ambiguous_update_target(
    "In deals page one button is not working",
    [
      {
        "path": "src/pages/Deals.jsx",
        "content": """
          export default function Deals() {
            return (
              <main>
                <button type="button">Create Action Plan</button>
                <button type="button">Reset Filter</button>
                <button type="button">Delete</button>
              </main>
            );
          }
        """,
      },
    ],
    target_resolution={
      "resolved_page": "Deals",
      "resolved_files": ["src/pages/Deals.jsx"],
      "resolved_button": "",
    },
  )

  assert clarification is not None
  assert clarification["missing_fields"] == ["button_identifier", "expected_behavior"]
  assert "Which button is not working" in clarification["clarification_question"]
  assert "Create Action Plan" in clarification["clarification_question"]


def test_specific_button_issue_does_not_require_ambiguity_clarification() -> None:
  clarification = clarification_for_ambiguous_update_target(
    "Create Action Plan button should open a modal instead of popup",
    PROJECT_FILES,
    target_resolution={
      "resolved_page": "Deals",
      "resolved_files": ["src/pages/Deals.jsx"],
      "resolved_button": "Create Action Plan",
    },
  )

  assert clarification is None


def test_fresh_ambiguous_prompt_still_requires_clarification_even_if_history_resolved_button() -> None:
  clarification = clarification_for_ambiguous_update_target(
    "In deals page one button is not working",
    [
      {
        "path": "src/pages/Deals.jsx",
        "content": """
          export default function Deals() {
            return (
              <main>
                <button type="button">Create Action Plan</button>
                <button type="button">Reset Filter</button>
              </main>
            );
          }
        """,
      },
    ],
    target_resolution={
      "resolved_page": "Deals",
      "resolved_files": ["src/pages/Deals.jsx"],
      "resolved_button": "Create Action Plan",
    },
  )

  assert clarification is not None
  assert clarification["missing_fields"] == ["button_identifier", "expected_behavior"]


def test_partial_button_phrase_resolves_to_live_button_label() -> None:
  target = build_target_resolution(
    "create action button is not working in deals page",
    [
      {
        "path": "src/pages/Deals.jsx",
        "content": """
          export default function Deals() {
            return (
              <main>
                <button type="button">Create Action Plan</button>
                <button type="button">Reset Filter</button>
              </main>
            );
          }
        """,
      },
    ],
  )

  assert target["resolved_files"] == ["src/pages/Deals.jsx"]
  assert target["resolved_button"] == "Create Action Plan"


def test_project_info_button_count_answer_uses_grounded_context_without_model() -> None:
  context = build_project_inspection_context(
    PROJECT_FILES,
    question="what are the buttons are there in that page total count",
    chat_messages=[
      {"role": "user", "content": "now explain about the operation hub page"},
      {"role": "assistant", "content": "The Operations page (`src/pages/Operations.jsx`) is the operation hub."},
    ],
  )
  state = GenerationPipelineState(
    user_prompt="what are the buttons are there in that page total count",
    intent="project_info",
    routing_result={
      "intent": "project_info",
      "next_tool": "summarize_current_project",
      "project_context": context,
    },
  )

  class ClientThatMustNotBeCalled:
    def generate_json(self, *args, **kwargs):
      raise AssertionError("grounded project-info response should not call the LLM")

  response = generate_conversation_response(state, ClientThatMustNotBeCalled())

  assert response["type"] == "project_info"
  assert "src/pages/Operations.jsx" in response["message"]
  assert "The page has 2 JSX buttons" in response["message"]
  assert "Run Audit" in response["message"]
  assert "Refresh operation hub" in response["message"]
  assert "**" not in response["message"]
  assert response["grounding"]["button_count"] == 2
  assert response["target_resolution"]["resolved_files"] == ["src/pages/Operations.jsx"]


def test_project_info_model_markdown_is_cleaned_for_chat_display() -> None:
  state = GenerationPipelineState(
    user_prompt="explain the operation hub page",
    intent="project_info",
    routing_result={
      "intent": "project_info",
      "next_tool": "summarize_current_project",
      "project_context": {},
    },
  )

  class MarkdownClient:
    def generate_json(self, *args, **kwargs):
      return {
        "message": "1. **Live Metrics Ribbon**\n- Shows **Uptime** and *Latency*.",
        "next_prompt_guidance": ["Ask for **button count**."],
      }

  response = generate_conversation_response(state, MarkdownClient())

  assert response["message"] == "1. Live Metrics Ribbon\n- Shows Uptime and Latency."
  assert response["next_prompt_guidance"] == ["Ask for button count."]


def test_project_info_model_response_hides_jsx_when_code_was_not_requested() -> None:
  state = GenerationPipelineState(
    user_prompt="explain the operation hub page",
    intent="project_info",
    routing_result={
      "intent": "project_info",
      "next_tool": "summarize_current_project",
      "project_context": {},
    },
  )

  class JsxDumpClient:
    def generate_json(self, *args, **kwargs):
      return {
        "message": (
          "The page is the operations area.\n"
          "```jsx\n<div className=\"p-4\">Operation Hub</div>\n```\n"
          "It has audit controls."
        ),
        "next_prompt_guidance": ["Ask for the button behavior."],
      }

  response = generate_conversation_response(state, JsxDumpClient())

  assert "Operation Hub" not in response["message"]
  assert "className" not in response["message"]
  assert "It has audit controls." in response["message"]


def test_project_info_model_response_keeps_code_when_requested() -> None:
  state = GenerationPipelineState(
    user_prompt="show me the JSX code for the operation hub page",
    intent="project_info",
    routing_result={
      "intent": "project_info",
      "next_tool": "summarize_current_project",
      "project_context": {},
    },
  )

  class CodeClient:
    def generate_json(self, *args, **kwargs):
      return {
        "message": "```jsx\n<div className=\"p-4\">Operation Hub</div>\n```",
        "next_prompt_guidance": ["Ask for an edit."],
      }

  response = generate_conversation_response(state, CodeClient())

  assert "className" in response["message"]
