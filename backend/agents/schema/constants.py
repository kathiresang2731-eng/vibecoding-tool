from __future__ import annotations


REQUIRED_RESPONSE_SECTIONS = [
  "multi_agent_system",
  "gemini_tool_calling_setup",
  "google_adk_usage",
  "orchestration_flow",
  "agent_to_agent_communication",
  "proactive_thinking",
]

REQUIRED_NESTED_PATHS = [
  ("orchestration_flow", "generated_website"),
  ("gemini_tool_calling_setup", "tools"),
  ("google_adk_usage", "adk_agents"),
  ("agent_to_agent_communication", "message_contract"),
  ("proactive_thinking", "recommended_next_actions"),
]
