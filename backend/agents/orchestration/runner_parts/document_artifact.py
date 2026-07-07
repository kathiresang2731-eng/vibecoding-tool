from __future__ import annotations

import json
from typing import Any

from backend.debug_trace import trace_print

from backend.agents.providers import GeminiProvider
from backend.agents.prompts import DOCUMENT_ARTIFACT_SYSTEM_INSTRUCTION, build_document_artifact_prompt
from ..runtime_metadata import apply_backend_routing_to_response
from backend.agents.orchestration.artifact_response import build_website_generation_response, normalize_document_artifact


def handle_document_artifact_branch(orchestrator: Any, state: Any) -> dict[str, Any]:
  learned_preferences = ""
  if orchestrator.tool_context is not None and orchestrator.user is not None:
    try:
      from ..memory.context import build_user_preferences_context_block

      learned_preferences = build_user_preferences_context_block(
        getattr(orchestrator.tool_context, "store", None),
        orchestrator.user,
        prompt=state.user_prompt,
        limit=6,
      )
    except Exception:
      learned_preferences = ""

  document_context = {
    "routing_result": state.routing_result,
    "adaptive_route": state.adaptive_route or {},
    "selected_agent": "Document Artifact Agent",
    "selected_action": "write_document_artifact",
    "workflow": "document_artifact_model_artifact",
    "learned_preferences": learned_preferences,
    "format_policy": (
      "Generate only document files (.md, .txt, .csv, .pdf). For PDF requests, generate polished "
      "document content for backend PDF export. Do not create website, React, Vite, or app scaffold files."
    ),
  }
  prompt = build_document_artifact_prompt(state.user_prompt, pipeline_context=json.dumps(document_context, indent=2))
  client = state.artifact_client or GeminiProvider()
  orchestrator._emit_progress(
    "agent.decision",
    "Chief Orchestrator selected the Document Artifact Agent for this request",
    status="completed",
    detail={
      "intent": "document_artifact",
      "selected_agent": "Document Artifact Agent",
      "selected_action": "write_document_artifact",
      "decision_source": "model_chief_orchestrator",
      "decision_reason": state.routing_result.get("reason"),
      "workflow": "document_artifact_model_artifact",
      "learned_preferences_included": bool(learned_preferences),
    },
  )
  orchestrator._emit_progress("generate_document_artifact.input", "Sending document request to the artifact model")
  state.raw_llm_response = client.generate_json(
    prompt,
    system_instruction=DOCUMENT_ARTIFACT_SYSTEM_INSTRUCTION,
    trace_label="generate_document_artifact",
    max_output_tokens=8192,
    chat_history=[],
  )
  orchestrator._emit_progress("generate_document_artifact.output", "Artifact model returned document files", status="completed")
  orchestrator._emit_progress("artifact.validation", "Validating generated document artifact")
  generated_website = normalize_document_artifact(state.raw_llm_response, user_prompt=state.user_prompt)
  orchestrator._emit_progress(
    "artifact.validated",
    f"Validated {len(generated_website.get('files') or [])} generated document files",
    status="completed",
    detail={"file_count": len(generated_website.get("files") or []), "paths": [file_item.get("path") for file_item in generated_website.get("files") or [] if isinstance(file_item, dict)]},
  )
  state.response = build_website_generation_response(state, generated_website=generated_website, artifact_response=state.raw_llm_response)
  apply_backend_routing_to_response(state)
  trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="document_artifact")
  return state.response["orchestration_flow"]
