from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.agents.schema import sanitize_generation_response
from .messages import (
  build_generation_conversation_message,
  build_update_conversation_message,
  extract_implementation_notes,
  list_from_notes,
)
from .flow import build_generation_communication
from .flow import build_generation_steps
from .logging import log_generated_website_tools
from .normalization import normalize_loose_generated_website
from backend.agents.orchestration.state import GenerationPipelineState


def build_website_generation_response(
  state: GenerationPipelineState,
  *,
  generated_website: dict[str, Any],
  artifact_response: dict[str, Any],
) -> dict[str, Any]:
  implementation_notes = extract_implementation_notes(artifact_response)
  generated_website = normalize_loose_generated_website(
    generated_website,
    intent=state.intent,
    prompt=state.user_prompt,
    artifact_response=artifact_response,
  )
  multi_agent_system = deepcopy(state.prepared_sections.get("multi_agent_system") or {})
  gemini_tool_calling_setup = deepcopy(state.prepared_sections.get("gemini_tool_calling_setup") or {})
  google_adk_usage = deepcopy(state.prepared_sections.get("google_adk_usage") or {})
  is_update = state.intent == "website_update"
  is_simple_code = state.intent == "simple_code"
  is_document_artifact = state.intent == "document_artifact"
  title = generated_website["title"]
  subheadline = generated_website["subheadline"]
  files = generated_website["files"]

  multi_agent_system["goal"] = (
    f"Update website artifact: {title}"
    if is_update
    else f"Write standalone code artifact: {title}"
    if is_simple_code
    else f"Write document artifact: {title}"
    if is_document_artifact
    else f"Generate website artifact: {title}"
  )
  multi_agent_system["intent"] = state.intent
  multi_agent_system["active_agent"] = "Simple Code Writer Agent" if is_simple_code else "Document Artifact Agent" if is_document_artifact else "Prompt Analyst Agent"
  multi_agent_system["routing_result"] = state.routing_result
  multi_agent_system["conversation_response"] = {
    "type": "simple_code" if is_simple_code else "document_artifact" if is_document_artifact else "update" if is_update else "generation",
    "message": (
      build_update_conversation_message(
        artifact_response=artifact_response,
        generated_website=generated_website,
      )
      if is_update
      else "Generated the requested document artifact."
      if is_document_artifact
      else build_generation_conversation_message(
        artifact_response=artifact_response,
        generated_website=generated_website,
      )
      if not is_simple_code
      else "Generated the requested standalone code file."
    ),
    "next_prompt_guidance": list_from_notes(
      implementation_notes,
      "recommended_next_actions",
      ["Review the preview.", "Ask for visual edits.", "Generate another section."],
    ),
  }
  shared_state = multi_agent_system.setdefault("shared_state", {})
  shared_state.update(
    {
      "prompt": state.user_prompt,
      "project_context": subheadline,
      "website_blueprint": title,
      "generated_files": (
        f"{len(files)} React/Tailwind file artifacts prepared for update."
        if is_update
        else f"{len(files)} standalone code file artifacts prepared."
        if is_simple_code
        else f"{len(files)} document file artifacts prepared."
        if is_document_artifact
        else f"{len(files)} React/Tailwind file artifacts prepared."
      ),
      "validation_report": (
        "Updated artifact normalized and merged with existing project files by backend before response."
        if is_update
        else "Code artifact normalized and saved by backend before response."
        if is_simple_code
        else "Document artifact normalized and saved by backend before response."
        if is_document_artifact
        else "Generated artifact normalized by backend before response."
      ),
    }
  )

  return sanitize_generation_response(
    {
      "multi_agent_system": multi_agent_system,
      "gemini_tool_calling_setup": gemini_tool_calling_setup,
      "google_adk_usage": google_adk_usage,
      "orchestration_flow": {
        "steps": build_generation_steps(state, generated_website),
        "generated_website": generated_website,
      },
      "agent_to_agent_communication": build_generation_communication(state, generated_website),
      "proactive_thinking": {
        "assumptions": list_from_notes(
          implementation_notes,
          "assumptions",
          ["The user wants the existing website updated while preserving unrelated files."]
          if is_update
          else ["The user wants a standalone code file, not a website."]
          if is_simple_code
          else ["The user wants a document artifact, not a website."]
          if is_document_artifact
          else ["The user wants a complete first version from one prompt."],
        ),
        "missing_information": list_from_notes(
          implementation_notes,
          "missing_information",
          []
          if is_simple_code or is_document_artifact
          else ["Exact brand assets", "Final copy", "Production integrations"],
        ),
        "predicted_risks": list_from_notes(
          implementation_notes,
          "predicted_risks",
          ["The requested language runtime may not be installed locally."]
          if is_simple_code
          else ["The requested document format may need review before sharing."]
          if is_document_artifact
          else ["Some copy may need brand-specific refinement."],
        ),
        "self_checks": list_from_notes(
          implementation_notes,
          "self_checks",
          ["Generated code artifact has at least one file"]
          if is_simple_code
          else ["Generated document artifact has at least one file"]
          if is_document_artifact
          else ["Generated website has sections", "Generated website has at least one file"],
        ),
        "recommended_next_actions": list_from_notes(
          implementation_notes,
          "recommended_next_actions",
          ["Review the updated preview.", "Request follow-up edits.", "Export the updated React files."]
          if is_update
          else ["Open the generated code file.", "Run it with the requested language runtime."]
          if is_simple_code
          else ["Open the generated document file.", "Review the content for final approval."]
          if is_document_artifact
          else ["Review the preview.", "Request design refinements.", "Export the generated React files."],
        ),
      },
    }
  )
