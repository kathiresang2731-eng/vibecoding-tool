from __future__ import annotations

import json
from typing import Any

from backend.debug_trace import trace_print

from backend.agents.domain_research import build_domain_research_context
from backend.agents.prompts import build_website_prompt
from backend.agents.providers import GeminiProvider
from backend.agents.adk_mapping import format_adk_mapping_for_prompt
from ..runtime_metadata import apply_backend_routing_to_response
from backend.agents.orchestration.artifact_response import build_website_generation_response, normalize_generated_website_artifact


def handle_legacy_fallback_branch(orchestrator: Any, state: Any) -> dict[str, Any]:
  orchestrator._emit_progress("legacy_generation.enabled", "Using explicit legacy one-shot generation fallback")
  state.prepared_sections["domain_research"] = build_domain_research_context(state.user_prompt)
  prompt = build_website_prompt(
    state.user_prompt,
    adk_mapping=format_adk_mapping_for_prompt(),
    pipeline_context=json.dumps(state.prepared_sections, indent=2),
    artifact_mode="website_update" if state.intent == "website_update" else "website_generation",
  )
  client = state.artifact_client or GeminiProvider()
  orchestrator._emit_progress("generate_website_artifact.input", "Sending website artifact request to Gemini/code provider")
  state.raw_llm_response = client.generate_json(
    prompt,
    trace_label="update_website_artifact" if state.intent == "website_update" else "generate_website_artifact",
  )
  orchestrator._emit_progress("generate_website_artifact.output", "Gemini returned a website artifact", status="completed")
  orchestrator._emit_progress("artifact.validation", "Validating generated sections, theme, and files")
  generated_website = normalize_generated_website_artifact(state.raw_llm_response)
  orchestrator._emit_progress(
    "artifact.validated",
    f"Validated {len(generated_website.get('files') or [])} files and {len(generated_website.get('sections') or [])} sections",
    status="completed",
    detail={"file_count": len(generated_website.get("files") or []), "section_count": len(generated_website.get("sections") or [])},
  )
  state.response = build_website_generation_response(state, generated_website=generated_website, artifact_response=state.raw_llm_response)
  apply_backend_routing_to_response(state)
  trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="legacy_generation")
  return state.response["orchestration_flow"]
