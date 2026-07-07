from __future__ import annotations

from typing import Any

from .common import ADK_APP_NAME
from .common import ADK_AGENT_ORDER


def _build_adk_agent_plan(model: str) -> dict[str, Any]:
  cleaned_model = model.strip() or "gemini-3.5-flash"
  agents_by_name = {
    "orchestrator": {
      "name": "orchestrator",
      "adk_type": "LlmAgent",
      "instruction": "Route the user turn, confirm risky work, and supervise legal flow transitions.",
      "tools": ["route_generation_action", "confirm_execution_brief"],
      "internal_agents": ["intent_router_agent", "supervisor_agent"],
    },
    "read_only_assistant_agent": {
      "name": "read_only_assistant_agent",
      "adk_type": "LlmAgent",
      "instruction": "Reply to greetings, questions, and project-info requests without creating website files.",
      "tools": ["handle_greeting", "answer_question", "answer_general_query", "search_web"],
      "internal_agents": ["conversation_agent"],
    },
    "simple_code_writer_agent": {
      "name": "simple_code_writer_agent",
      "adk_type": "LlmAgent",
      "instruction": "Generate standalone code artifacts for simple_code turns only.",
      "tools": ["generate_simple_code_file"],
      "internal_agents": ["simple_code_writer_agent"],
    },
    "document_artifact_agent": {
      "name": "document_artifact_agent",
      "adk_type": "LlmAgent",
      "instruction": "Generate Markdown, TXT, CSV, documentation, planning, research, and PDF-ready document artifacts.",
      "tools": ["generate_document_artifact"],
      "internal_agents": ["document_artifact_agent"],
    },
    "context_agent": {
      "name": "context_agent",
      "adk_type": "LlmAgent",
      "instruction": "Load project memory/files and prepare the smallest useful scope or plan before implementation.",
      "tools": ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "PERSIST_PROJECT_MEMORY"],
      "internal_agents": ["memory_agent", "prompt_analyst_agent", "planner_agent"],
    },
    "website_builder_agent": {
      "name": "website_builder_agent",
      "adk_type": "LlmAgent",
      "instruction": "Generate or update website files through the selected builder strategy.",
      "tools": ["READ_PROJECT_FILES", "WRITE_PROJECT_FILES"],
      "internal_agents": ["code_agent", "scoped_update_agent", "streaming_file_agent"],
    },
    "quality_gate_service": {
      "name": "quality_gate_service",
      "adk_type": "LlmAgent",
      "instruction": "Validate artifacts, build staged previews, and run visual/runtime QA before commit.",
      "tools": ["VALIDATE_PROJECT_ARTIFACT", "BUILD_STAGED_PROJECT_PREVIEW", "BUILD_PROJECT_PREVIEW", "RUN_PREVIEW_VISUAL_QA"],
      "internal_agents": ["ux_review_agent", "accessibility_agent", "validation_agent", "preview_agent", "visual_qa_agent"],
    },
    "save_memory_service": {
      "name": "save_memory_service",
      "adk_type": "BaseAgent",
      "instruction": "Commit accepted files and persist project memory after successful completion.",
      "tools": ["WRITE_PROJECT_FILES", "PERSIST_PROJECT_MEMORY"],
      "internal_agents": ["commit_agent", "memory_agent"],
    },
  }
  return {
    "app_name": ADK_APP_NAME,
    "model": cleaned_model,
    "root_agent": "orchestrator",
    "execution_strategy": "Gemini controls canonical phase agents and can request backend FunctionTool calls; Python remains the source of truth for tool execution and commits. Internal agent names are metadata only.",
    "agents": [agents_by_name[name] for name in ADK_AGENT_ORDER],
  }


def build_adk_agent_plan(model: str) -> dict[str, Any]:
  return _build_adk_agent_plan(model)
