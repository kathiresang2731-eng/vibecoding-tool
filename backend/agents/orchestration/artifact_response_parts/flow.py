from __future__ import annotations

from typing import Any

from backend.agents.orchestration.state import GenerationPipelineState
from .normalization import normalize_loose_generated_website


def build_generation_steps(state: GenerationPipelineState, generated_website: dict[str, Any]) -> list[dict[str, Any]]:
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
  )
  is_update = state.intent == "website_update"
  is_simple_code = state.intent == "simple_code"
  title = generated_website["title"]
  sections = generated_website["sections"]
  files = generated_website["files"]
  return [
    {
      "step": 1,
      "name": "Tool-based intent routing",
      "owner_agent": "Intent Router Agent",
      "input": state.user_prompt,
      "actions": [
        "Call route_generation_action",
        "Select generate_simple_code_file"
        if is_simple_code
        else "Select analyze_update_request"
        if state.intent == "website_update"
        else "Select analyze_prompt",
      ],
      "output": state.routing_result,
    },
    {
      "step": 2,
      "name": "Code request analysis" if is_simple_code else "Update request analysis" if is_update else "Prompt analysis",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Prompt Analyst Agent",
      "input": state.user_prompt,
      "actions": (
        ["Infer language", "Infer filename", "Prepare code-only artifact"]
        if is_simple_code
        else
        ["Identify requested changes", "Map update to existing project files"]
        if is_update
        else ["Identify website type", "Extract audience and content goals"]
      ),
      "output": title,
    },
    {
      "step": 3,
      "name": "Standalone code planning" if is_simple_code else "Predictive website planning",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Predictive Planning Agent",
      "input": sections,
      "actions": ["Choose code structure", "Choose input/output behavior"] if is_simple_code else ["Plan section order", "Choose conversion path"],
      "output": [section["name"] for section in sections],
    },
    {
      "step": 4,
      "name": "Standalone code generation" if is_simple_code else "Prescriptive update artifact generation" if is_update else "Prescriptive artifact generation",
      "owner_agent": "Simple Code Writer Agent" if is_simple_code else "Prescriptive Builder Agent",
      "input": title,
      "actions": (
        ["Generate runnable code file", "Skip website shell"]
        if is_simple_code
        else
        ["Generate changed React/Tailwind files", "Preserve unrelated project files"]
        if is_update
        else ["Generate preview content", "Generate React and Tailwind files"]
      ),
      "output": f"{len(files)} files prepared",
    },
    {
      "step": 5,
      "name": "Validation",
      "owner_agent": "Diagnostic UX Agent",
      "input": generated_website,
      "actions": ["Check generated file artifact", "Normalize missing artifact fields"]
      if is_simple_code
      else ["Check required preview data", "Normalize missing artifact fields"],
      "output": "Generated code artifact is response-ready." if is_simple_code else "Generated website artifact is response-ready.",
    },
  ]


def build_generation_communication(state: GenerationPipelineState, generated_website: dict[str, Any]) -> dict[str, Any]:
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
  )
  is_update = state.intent == "website_update"
  title = generated_website["title"]
  sections = generated_website["sections"]
  files = generated_website["files"]
  return {
    "message_contract": {
      "from_agent": "Prompt Analyst Agent",
      "to_agent": "Prescriptive Builder Agent",
      "sender": "Prompt Analyst Agent",
      "receiver": "Prescriptive Builder Agent",
      "task": (
        "Update the existing website artifact from the routed prompt."
        if is_update
        else "Build the website artifact from the routed prompt."
      ),
      "input": {
        "prompt": state.user_prompt,
        "routing_result": state.routing_result,
        "sections": [section["name"] for section in sections],
      },
      "output": {
        "website_title": title,
        "file_paths": [file_item["path"] for file_item in files if isinstance(file_item, dict)],
      },
      "next_action": "generate_update_artifact" if is_update else "generate_project_artifact",
      "context": {
        "prompt": state.user_prompt,
        "routing_result": state.routing_result,
        "website_title": title,
      },
      "expected_output": {
        "generated_website": (
          "Updated preview data and changed file artifacts"
          if is_update
          else "Complete preview data and file artifacts"
        ),
      },
      "confidence": 0.92,
      "risks": (
        ["Requested update may depend on project files outside the generated artifact surface."]
        if is_update
        else ["User may want brand-specific details that were not included in the prompt."]
      ),
    },
    "handoff_rules": [
      "Intent Router Agent must run before generation.",
      "Prompt Analyst Agent passes structured context to planning.",
      "Predictive Planning Agent selects sections before file generation.",
      "Diagnostic UX Agent validates the normalized website artifact.",
    ],
    "example_messages": [
      {
        "from_agent": "Prompt Analyst Agent",
        "to_agent": "Predictive Planning Agent",
        "message": {
          "prompt": state.user_prompt,
          "website_title": title,
          "sections": [section["name"] for section in sections],
        },
      }
    ],
  }
