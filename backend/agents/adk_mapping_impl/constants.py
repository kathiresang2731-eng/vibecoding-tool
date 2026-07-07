from __future__ import annotations


ADK_AGENT_MAPPING = [
  {
    "adk_type": "SequentialAgent",
    "name": "worktual_website_pipeline",
    "purpose": "Runs prompt intake, planning, generation, validation, and packaging in a predictable order.",
  },
  {
    "adk_type": "LlmAgent",
    "name": "prompt_analyst_agent",
    "purpose": "Understands the user's prompt, audience, tone, website type, and missing context.",
  },
  {
    "adk_type": "ParallelAgent",
    "name": "planning_parallel_agent",
    "purpose": "Runs UX planning, content planning, and technical planning in parallel.",
  },
  {
    "adk_type": "LlmAgent",
    "name": "ui_generation_agent",
    "purpose": "Creates the responsive React and Tailwind component plan.",
  },
  {
    "adk_type": "LoopAgent",
    "name": "validation_repair_loop",
    "purpose": "Repeats validation and repair until the generated website meets quality checks.",
  },
  {
    "adk_type": "AgentTool",
    "name": "code_generator_tool_agent",
    "purpose": "Allows the orchestrator to call the code generator as a tool.",
  },
  {
    "adk_type": "BaseAgent",
    "name": "deployment_packager_agent",
    "purpose": "Packages generated files and next actions for export or preview deployment.",
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
