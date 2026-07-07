from __future__ import annotations


ADK_AGENT_MAPPING = [
  {
    "adk_type": "SequentialAgent",
    "name": "orchestrator",
    "purpose": "Routes the user turn and controls the legal phase order before any generation or file write.",
    "internal_agents": ["intent_router_agent", "supervisor_agent"],
  },
  {
    "adk_type": "LlmAgent",
    "name": "read_only_assistant_agent",
    "purpose": "Answers greetings, questions, and project-info requests without file mutation.",
    "internal_agents": ["conversation_agent"],
  },
  {
    "adk_type": "LlmAgent",
    "name": "simple_code_writer_agent",
    "purpose": "Generates standalone code artifacts outside website generation.",
    "internal_agents": ["simple_code_writer_agent"],
  },
  {
    "adk_type": "LlmAgent",
    "name": "document_artifact_agent",
    "purpose": "Generates Markdown, TXT, CSV, research/planning, and PDF-ready document artifacts.",
    "internal_agents": ["document_artifact_agent"],
  },
  {
    "adk_type": "LlmAgent",
    "name": "context_agent",
    "purpose": "Loads project memory/files and prepares the smallest useful scope or plan.",
    "internal_agents": ["memory_agent", "prompt_analyst_agent", "planner_agent"],
  },
  {
    "adk_type": "LlmAgent",
    "name": "website_builder_agent",
    "purpose": "Generates or updates website files through the selected builder strategy.",
    "internal_agents": ["code_agent", "scoped_update_agent", "streaming_file_agent"],
  },
  {
    "adk_type": "LoopAgent",
    "name": "quality_gate_service",
    "purpose": "Validates artifacts, staged previews, visual QA, and repair readiness before commit.",
    "internal_agents": ["ux_review_agent", "accessibility_agent", "validation_agent", "preview_agent", "visual_qa_agent"],
  },
  {
    "adk_type": "BaseAgent",
    "name": "save_memory_service",
    "purpose": "Commits accepted files and persists project memory after successful completion.",
    "internal_agents": ["commit_agent", "memory_agent"],
  },
]

ADK_RUNTIME_PLAN = [
  "Keep the current lightweight Python API for V1.",
  "Build a Google ADK runtime payload for every generation response.",
  "Use dry-run ADK event projection when google-adk is unavailable locally.",
  "Create the real ADK Runner, SessionService, and MemoryService when google-adk is installed.",
  "Use Gemini for routing, conversation handling, planning, reviews, supervision, memory decisions, generation, and repair.",
  "Keep Python backend tools as the source of truth for file IO, preview building, QA, and memory persistence.",
]

ADK_MAPPING_NOTES = [
  "Google ADK runtime metadata is generated under google_adk_usage for every backend generation.",
  "Live ADK Runner execution requires the google-adk package to be installed in the backend environment.",
  "Dry-run mode validates the ADK agent order, backend tool bindings, session payload, and projected events.",
  "The source-of-truth runtime uses Gemini for control/artifact model calls and Python for backend tool execution.",
]
