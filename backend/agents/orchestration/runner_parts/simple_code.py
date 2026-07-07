from __future__ import annotations

import json
from typing import Any

from backend.debug_trace import trace_print

from backend.agents.providers import GeminiProvider
from backend.agents.prompts import SIMPLE_CODE_SYSTEM_INSTRUCTION, build_minimal_simple_code_prompt, build_simple_code_prompt
from backend.agents.request_complexity import ADAPTIVE_ROUTE_SMALL_CODE
from ..runtime_metadata import apply_backend_routing_to_response
from backend.agents.project_workspace import standalone_code_source_files
from ..provider_utils import is_artifact_intent
from backend.agents.orchestration.artifact_response import build_website_generation_response, normalize_simple_code_artifact
from .sections import existing_standalone_code_context, should_include_existing_simple_code_context


def handle_simple_code_branch(orchestrator: Any, state: Any) -> dict[str, Any]:
  existing_project_files: list[dict[str, Any]] = []
  if orchestrator.project_id and orchestrator.tool_context is not None and orchestrator.user is not None:
    store = getattr(orchestrator.tool_context, "store", None)
    if store is not None and hasattr(store, "list_files"):
      try:
        existing_project_files = store.list_files(orchestrator.project_id, orchestrator.user)
      except Exception:
        existing_project_files = []
  include_existing_code_context = should_include_existing_simple_code_context(state.user_prompt)
  existing_code_files = existing_standalone_code_context(existing_project_files) if include_existing_code_context else []
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
  adaptive_route = state.adaptive_route or {}
  simple_code_context = {
    "routing_result": state.routing_result,
    "adaptive_route": adaptive_route,
    "selected_agent": "Simple Code Writer Agent",
    "selected_action": "write_standalone_code_file",
    "workflow": "simple_code_model_artifact",
    "existing_standalone_files": existing_code_files,
    "existing_context_included": include_existing_code_context,
    "learned_preferences": learned_preferences,
    "code_update_policy": (
      "If the user asks to change, simplify, convert, fix, or update existing standalone code, "
      "use existing_standalone_files as the target context and return only the changed standalone code file(s)."
    ),
  }
  prompt_builder = build_minimal_simple_code_prompt if adaptive_route.get("route") == ADAPTIVE_ROUTE_SMALL_CODE else build_simple_code_prompt
  prompt = prompt_builder(state.user_prompt, pipeline_context=json.dumps(simple_code_context, indent=2))
  client = state.artifact_client or GeminiProvider()
  orchestrator._emit_progress(
    "agent.decision",
    "Chief Orchestrator selected the Simple Code Writer Agent for this request",
    status="completed",
    detail={
      "intent": "simple_code",
      "selected_agent": "Simple Code Writer Agent",
      "selected_action": "write_standalone_code_file",
      "decision_source": "model_chief_orchestrator",
      "decision_reason": state.routing_result.get("reason"),
      "workflow": "simple_code_model_artifact",
      "adaptive_route": adaptive_route,
      "existing_code_files": [item["path"] for item in existing_code_files],
      "existing_context_included": include_existing_code_context,
      "learned_preferences_included": bool(learned_preferences),
    },
  )
  orchestrator._emit_progress("generate_simple_code_file.input", "Sending standalone code request to the artifact model")
  state.raw_llm_response = client.generate_json(
    prompt,
    system_instruction=SIMPLE_CODE_SYSTEM_INSTRUCTION,
    trace_label="generate_simple_code_file",
    max_output_tokens=4096,
    chat_history=[],
  )
  orchestrator._emit_progress("generate_simple_code_file.output", "Artifact model returned standalone code files", status="completed")
  orchestrator._emit_progress("artifact.validation", "Validating generated code file artifact")
  generated_website = normalize_simple_code_artifact(state.raw_llm_response)
  orchestrator._emit_progress(
    "artifact.validated",
    f"Validated {len(generated_website.get('files') or [])} generated code files",
    status="completed",
    detail={"file_count": len(generated_website.get("files") or []), "paths": [file_item.get("path") for file_item in generated_website.get("files") or [] if isinstance(file_item, dict)]},
  )
  state.response = build_website_generation_response(state, generated_website=generated_website, artifact_response=state.raw_llm_response)
  apply_backend_routing_to_response(state)
  trace_print("EXIT", file=__file__, class_name="WorktualGenerationOrchestrator", function="orchestration_flow", branch="simple_code")
  return state.response["orchestration_flow"]
