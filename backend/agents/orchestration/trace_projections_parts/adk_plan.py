from __future__ import annotations

from typing import Any

from .common import ADK_APP_NAME


def _build_adk_agent_plan(model: str) -> dict[str, Any]:
  cleaned_model = model.strip() or "gemini-3.5-flash"
  return {
    "app_name": ADK_APP_NAME,
    "model": cleaned_model,
    "root_agent": "supervisor_agent",
    "execution_strategy": "Gemini controls specialist agents and can request backend FunctionTool calls; Python remains the source of truth for tool execution and commits.",
    "agents": [
      {"name": "intent_router_agent", "adk_type": "LlmAgent", "instruction": "Route the user turn to greeting, detail collection, or website generation.", "tools": ["route_generation_action"]},
      {"name": "supervisor_agent", "adk_type": "Agent", "instruction": "Use Gemini to coordinate website planning, validation, repair routing, and memory updates.", "tools": []},
      {"name": "conversation_agent", "adk_type": "LlmAgent", "instruction": "Reply to greeting or incomplete prompts without creating website files.", "tools": []},
      {"name": "memory_agent", "adk_type": "LlmAgent", "instruction": "Load project memory before planning and persist concise project memory after completion.", "tools": ["load_memory", "LOAD_PROJECT_MEMORY", "PERSIST_PROJECT_MEMORY"]},
      {"name": "prompt_analyst_agent", "adk_type": "LlmAgent", "instruction": "Extract audience, brand, sections, style, business goal, and implementation constraints.", "tools": []},
      {"name": "planner_agent", "adk_type": "LlmAgent", "instruction": "Plan the website structure and component responsibilities before code is written.", "tools": []},
      {"name": "ux_review_agent", "adk_type": "LlmAgent", "instruction": "Review planned website UX for user flow, conversion clarity, responsive behavior, and content gaps.", "tools": []},
      {"name": "accessibility_agent", "adk_type": "LlmAgent", "instruction": "Review planned UI for contrast, semantics, keyboard flow, and mobile text fit.", "tools": []},
      {"name": "code_agent", "adk_type": "LlmAgent", "instruction": "Call the selected Gemini generation model only for React, CSS, config, and public asset artifact generation or update.", "tools": ["READ_PROJECT_FILES", "WRITE_PROJECT_FILES"]},
      {"name": "validation_agent", "adk_type": "LlmAgent", "instruction": "Validate generated artifacts, paths, sections, theme, and required files before preview builds.", "tools": ["VALIDATE_PROJECT_ARTIFACT"]},
      {"name": "preview_agent", "adk_type": "LlmAgent", "instruction": "Build the generated project preview and return build status, logs, and preview URL.", "tools": ["BUILD_STAGED_PROJECT_PREVIEW", "BUILD_PROJECT_PREVIEW"]},
      {"name": "visual_qa_agent", "adk_type": "LlmAgent", "instruction": "Run backend preview integrity QA before generated files are committed.", "tools": ["RUN_PREVIEW_VISUAL_QA"]},
      {"name": "repair_agent", "adk_type": "LlmAgent", "instruction": "Call the selected Gemini generation model for code repair from validation or preview errors, then restore previous files if repair fails.", "tools": ["WRITE_PROJECT_FILES", "BUILD_PROJECT_PREVIEW"]},
    ],
  }


def build_adk_agent_plan(model: str) -> dict[str, Any]:
  return _build_adk_agent_plan(model)
