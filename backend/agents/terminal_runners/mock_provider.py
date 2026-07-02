from __future__ import annotations

from typing import Any

from ..providers.mock import MockProvider, default_mock_artifact


class TerminalMockProvider(MockProvider):
  """Deterministic mock responses keyed by agent trace labels for terminal testing."""

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
    if trace_label == "prompt_analyst_agent":
      return self._prompt_analyst_payload(prompt)
    if trace_label == "planner_agent":
      return self._planner_payload(prompt)
    if trace_label in {"ux_review_agent", "accessibility_review_agent"}:
      return {
        "status": "reviewed",
        "issues": [],
        "recommendations": ["Terminal mock review passed."],
      }
    if trace_label == "update_analysis_agent":
      return {
        "summary": "Apply the requested website update.",
        "update_mode": "content_patch",
        "request_kind": "content",
        "execution_strategy": "scoped_patch",
        "scope": "small",
        "reason": "Terminal mock update analysis.",
        "candidate_files": ["src/App.jsx"],
        "candidate_new_files": [],
        "scoped_update_tasks": [],
      }
    if trace_label.startswith("create_dynamic_agent_"):
      capability = trace_label.removeprefix("create_dynamic_agent_")
      return {
        "id": f"{capability}-terminal-agent",
        "name": f"{capability.replace('_', ' ').title()} Agent",
        "role": f"Terminal mock specialist for {capability}",
        "capabilities": [capability],
        "supported_domains": ["any"],
        "system_prompt": f"You are a mock {capability} specialist.",
      }
    if trace_label == "supervisor_agent":
      return self.routing_payload
    return super().generate_json(
      prompt,
      system_instruction=system_instruction,
      trace_label=trace_label,
      tools=tools,
      response_schema=response_schema,
      max_output_tokens=max_output_tokens,
      chat_history=chat_history,
      prompt_fragments_used=prompt_fragments_used,
      selected_files=selected_files,
      memory_items_used=memory_items_used,
    )

  def _prompt_analyst_payload(self, prompt: str) -> dict[str, Any]:
    topic = prompt.strip() or "website"
    return {
      "summary": f"Build a polished {topic} with clear sections and strong conversion flow.",
      "website_type": topic,
      "audience": "General visitors",
      "primary_goal": "Present the offering clearly and drive engagement",
      "tone": "Professional and welcoming",
      "required_sections": ["Hero", "Features", "About", "Contact"],
      "style_direction": "Clean modern layout with strong typography",
      "constraints": ["Responsive", "Accessible contrast"],
      "missing_information": [],
    }

  def _planner_payload(self, prompt: str) -> dict[str, Any]:
    return {
      "layout_strategy": "Single-page marketing site with anchored sections",
      "sections": [
        {"name": "Hero", "purpose": "Introduce the site", "content_notes": prompt[:120]},
        {"name": "Features", "purpose": "Highlight key value", "content_notes": "3 feature cards"},
        {"name": "Contact", "purpose": "Capture leads", "content_notes": "Simple contact CTA"},
      ],
      "interactions": ["Smooth scroll navigation", "Primary CTA above the fold"],
      "quality_checks": ["Mobile layout", "Readable headings", "Accessible buttons"],
      "implementation_notes": ["Use existing React scaffold", "Keep components small"],
    }


def build_terminal_mock_artifact(prompt: str) -> dict[str, Any]:
  artifact = default_mock_artifact()
  website = artifact.get("generated_website")
  if isinstance(website, dict):
    website["headline"] = f"Terminal mock build: {prompt[:80]}"
  return artifact
