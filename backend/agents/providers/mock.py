from __future__ import annotations

from typing import Any

from .constants import DUAL_PROVIDER_ROLE


class MockProvider:
  name = "mock"
  provider_role = DUAL_PROVIDER_ROLE

  def __init__(
    self,
    *,
    artifact_payload: dict[str, Any] | None = None,
    routing_payload: dict[str, Any] | None = None,
    conversation_payload: dict[str, Any] | None = None,
  ) -> None:
    self.artifact_payload = artifact_payload or default_mock_artifact()
    self.routing_payload = routing_payload or {
      "intent": "website_generation",
      "next_action": "generate_website",
      "next_tool": "analyze_prompt",
      "reason": "Mock provider selected website generation.",
    }
    self.conversation_payload = conversation_payload or {
      "type": "needs_more_detail",
      "message": "Share the website type, audience, style, and required sections.",
      "next_prompt_guidance": ["Website type", "Audience", "Sections", "Visual style"],
    }

  def generate_json(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "mock_generate_json",
    tools: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | None = None,
    max_output_tokens: int | None = None,
    chat_history: list[dict[str, Any]] | None = None,
    prompt_fragments_used: list[str] | None = None,
    selected_files: list[str] | None = None,
    memory_items_used: int = 0,
  ) -> dict[str, Any]:
    if "You are the route_generation_action tool" in prompt or "Repair the output" in prompt:
      return self.routing_payload
    if "Write the assistant response for Worktual AI Dev" in prompt:
      return self.conversation_payload
    return self.artifact_payload

  def generate_json_with_search(
    self,
    prompt: str,
    *,
    system_instruction: str | None = None,
    trace_label: str = "mock_search_generate_json",
  ) -> dict[str, Any]:
    return self.conversation_payload


def default_mock_artifact() -> dict[str, Any]:
  return {
    "generated_website": {
      "title": "Mock Landing Page",
      "headline": "Launch a polished website from one prompt",
      "subheadline": "A deterministic mock artifact for local development.",
      "primary_cta": "Start building",
      "secondary_cta": "View preview",
      "preview_html": "",
      "sections": [
        {
          "name": "Hero",
          "purpose": "Introduce the generated website.",
          "content": "A focused hero section for the generated site.",
          "items": ["Headline", "Subheadline", "CTA"],
        }
      ],
      "files": [
        {
          "path": "src/App.jsx",
          "purpose": "Generated React app shell.",
          "code": (
            "export default function App() {\n"
            "  return (\n"
            "    <main className=\"min-h-screen px-6 py-16\">\n"
            "      <p className=\"text-sm font-bold uppercase tracking-normal\">Mock Landing Page</p>\n"
            "      <h1 className=\"mt-4 max-w-3xl text-5xl font-black\">Launch a polished website from one prompt</h1>\n"
            "      <p className=\"mt-5 max-w-2xl text-lg\">A deterministic local artifact for builder development.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
          ),
        }
      ],
    },
    "implementation_notes": {
      "assumptions": ["Mock provider is active."],
      "missing_information": ["Live provider output"],
      "predicted_risks": ["Mock output is intentionally simple."],
      "self_checks": ["Includes src/App.jsx"],
      "recommended_next_actions": ["Edit files", "Build preview"],
    },
  }
