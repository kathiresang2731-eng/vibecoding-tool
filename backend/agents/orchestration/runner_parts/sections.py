from __future__ import annotations

from typing import Any

from backend.agents.adk_mapping import get_adk_mapping
from backend.agents.canonical_roles import canonical_role_for_agent
from backend.agents.prompt_context import current_user_prompt
from backend.agents.project_workspace import standalone_code_source_files
from ..provider_utils import is_artifact_intent, provider_name
from ..runtime_metadata import require_pipeline_response
from ..tool_registry import log_tool_call
from backend.agents.orchestration.constants import DEFAULT_TOOL_REGISTRY, PIPELINE_STAGE_ORDER, VISIBLE_AGENT_TEAM
from backend.agents.orchestration.state import GenerationPipelineState

_SIMPLE_CODE_CONTEXT_FILE_LIMIT = 4
_SIMPLE_CODE_CONTEXT_CHAR_LIMIT = 16_000
_SIMPLE_CODE_EXISTING_CONTEXT_MARKERS = (
  "this code",
  "existing code",
  "current code",
  "above code",
  "previous code",
  "change ",
  "update ",
  "modify ",
  "edit ",
  "fix ",
  "debug ",
  "simplify",
  "simplified",
  "convert ",
  "rewrite ",
  "refactor ",
  "remove ",
  "delete ",
  "without comments",
  "remove comments",
  "add comments",
)


def existing_standalone_code_context(files: list[dict[str, Any]] | None) -> list[dict[str, str]]:
  context_files: list[dict[str, str]] = []
  used_chars = 0
  for item in standalone_code_source_files(files)[:_SIMPLE_CODE_CONTEXT_FILE_LIMIT]:
    path = str(item.get("path") or "").strip()
    content = item.get("content")
    if content is None:
      content = item.get("code")
    text = content if isinstance(content, str) else ""
    remaining = max(_SIMPLE_CODE_CONTEXT_CHAR_LIMIT - used_chars, 0)
    if remaining <= 0:
      break
    snippet = text[:remaining]
    used_chars += len(snippet)
    context_files.append({"path": path, "content": snippet})
  return context_files


def should_include_existing_simple_code_context(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  if not lowered:
    return False
  return any(marker in lowered for marker in _SIMPLE_CODE_EXISTING_CONTEXT_MARKERS)


def compatibility_export(name: str, fallback: Any) -> Any:
  try:
    from .. import orchestrator as compatibility_orchestrator

    return getattr(compatibility_orchestrator, name, fallback)
  except Exception:
    return fallback


def build_multi_agent_system(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  is_greeting = state.intent == "greeting"
  needs_more_detail = state.intent == "needs_more_detail"
  needs_confirmation = state.intent == "needs_confirmation"
  is_simple_code = state.intent == "simple_code"
  is_document_artifact = state.intent == "document_artifact"
  is_update = state.intent == "website_update"
  active_agent = (
    "Intent Router Agent"
    if is_greeting
    else "Requirement Confirmation Agent"
    if needs_confirmation
    else "Simple Code Writer Agent"
    if is_simple_code
    else "Document Artifact Agent"
    if is_document_artifact
    else "Intent Router Agent"
    if needs_more_detail
    else "Prompt Analyst Agent"
  )
  section = {
    "goal": (
      "Use the Intent Router greeting tool to respond and collect the website brief."
      if is_greeting
      else "Present the execution brief and wait for explicit user confirmation."
      if needs_confirmation
      else "Ask for more website details before generation."
      if needs_more_detail
      else "Write a standalone code file directly from the user prompt."
      if is_simple_code
      else "Write a document artifact directly from the user prompt."
      if is_document_artifact
      else "Update the existing website from the user prompt."
      if is_update
      else "Generate a complete website from the user prompt."
    ),
    "intent": state.intent,
    "agents": VISIBLE_AGENT_TEAM,
    "active_agent": active_agent,
    "active_canonical_role": canonical_role_for_agent(active_agent),
    "routing_result": state.routing_result,
    "conversation_response": {},
    "shared_state": {
      "prompt": state.user_prompt,
      "project_context": (
        "Greeting received; waiting for website description."
        if is_greeting
        else "Execution brief prepared; waiting for explicit user confirmation."
        if needs_confirmation
        else "More details needed before generation."
        if needs_more_detail
        else "Standalone code request; code artifact generation is selected."
        if is_simple_code
        else "Document request; document artifact generation is selected."
        if is_document_artifact
        else "Existing project update requested; pending update analysis."
        if is_update
        else "Pending prompt analysis"
      ),
      "website_blueprint": (
        "Not started until the user describes the website."
        if is_greeting or needs_more_detail
        else "Waiting for user confirmation before execution."
        if needs_confirmation
        else "No website blueprint needed for a standalone code file."
        if is_simple_code
        else "No website blueprint needed for a document artifact."
        if is_document_artifact
        else "Pending update plan"
        if is_update
        else "Pending predictive planning"
      ),
      "generated_files": (
        "No website files generated before explicit confirmation."
        if not is_artifact_intent(state.intent)
        else "Pending standalone code artifact"
        if is_simple_code
        else "Pending document artifact"
        if is_document_artifact
        else "Pending updated project artifact"
        if is_update
        else "Pending orchestration output"
      ),
      "validation_report": (
        "Conversation turn handled before generation validation."
        if not is_artifact_intent(state.intent)
        else "Pending code artifact validation."
        if is_simple_code
        else "Pending document artifact validation."
        if is_document_artifact
        else "Pending diagnostic checks"
      ),
    },
  }
  state.prepared_sections["multi_agent_system"] = section
  return section


def build_gemini_tool_calling_setup(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  if state.intent == "greeting":
    tool_sequence = ["route_generation_action", "handle_greeting"]
  elif state.intent == "needs_more_detail":
    tool_sequence = ["route_generation_action", "request_website_details"]
  elif state.intent == "needs_confirmation":
    tool_sequence = ["route_generation_action", "confirm_execution_brief"]
  elif state.intent == "simple_code":
    tool_sequence = ["route_generation_action", "generate_simple_code_file", "validate_generated_website"]
  elif state.intent == "document_artifact":
    tool_sequence = ["route_generation_action", "generate_document_artifact", "validate_generated_website"]
  elif state.intent == "website_update":
    tool_sequence = [
      "route_generation_action",
      "READ_PROJECT_FILES",
      "LOAD_PROJECT_MEMORY",
      "analyze_update_request",
      "generate_update_artifact",
      "validate_generated_website",
    ]
  else:
    tool_sequence = [
      "route_generation_action",
      "analyze_prompt",
      "generate_website_files",
      "validate_generated_website",
    ]
  section = {
    "tool_policy": "Gemini classifies chat/routing turns, can request backend tools through native function calling, and generates website artifacts.",
    "provider": "gemini-native-control-artifact",
    "control_provider": provider_name(state.control_client),
    "artifact_provider": provider_name(state.artifact_client),
    "native_tool_calling": {
      "status": "enabled",
      "mode": "VALIDATED",
      "safety_boundary": "Python validates tool order, arguments, preview readiness, and file commits.",
    },
    "tools": DEFAULT_TOOL_REGISTRY,
    "tool_call_sequence": tool_sequence,
  }
  log_tool_call("tool_calling_setup", "sequence", {"intent": state.intent, "tool_call_sequence": tool_sequence})
  state.prepared_sections["gemini_tool_calling_setup"] = section
  return section


def build_google_adk_usage(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  section = get_adk_mapping()
  section["adk_agents"] = [
    {"adk_type": "LlmAgent", "name": "intent_router_agent", "purpose": "Calls routing and conversation tools, including handle_greeting, before any website generation action."},
    {"adk_type": "AgentTool", "name": "route_generation_action_tool", "purpose": "Callable routing tool used before any website generation action."},
    {"adk_type": "AgentTool", "name": "handle_greeting_tool", "purpose": "Callable greeting response tool owned by intent_router_agent before website generation."},
    {"adk_type": "LlmAgent", "name": "simple_code_writer_agent", "purpose": "Generates standalone code files directly for simple_code turns."},
    {"adk_type": "AgentTool", "name": "generate_simple_code_file_tool", "purpose": "Callable code artifact generator used when the router selects simple_code."},
    {"adk_type": "LlmAgent", "name": "document_artifact_agent", "purpose": "Generates documentation, reports, plans, research briefs, CSV, TXT, and PDF-ready Markdown files."},
    {"adk_type": "AgentTool", "name": "generate_document_artifact_tool", "purpose": "Callable document artifact generator used when the router selects document_artifact."},
    *section["adk_agents"],
  ]
  state.prepared_sections["google_adk_usage"] = section
  return section


def build_agent_to_agent_communication(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  response = require_pipeline_response(state)
  communication = response["agent_to_agent_communication"]
  communication["backend_stage_order"] = list(PIPELINE_STAGE_ORDER)
  state.prepared_sections["agent_to_agent_communication"] = communication
  return communication


def build_proactive_thinking(orchestrator: Any, state: GenerationPipelineState) -> dict[str, Any]:
  response = require_pipeline_response(state)
  proactive = response["proactive_thinking"]
  proactive["backend_execution"] = {
    "pipeline_stage_order": list(PIPELINE_STAGE_ORDER),
    "completed_stages": [entry for entry in state.stage_trace if entry["status"] == "completed"],
  }
  return proactive
