from __future__ import annotations


ORCHESTRATION_NODE_MAP = [
  {
    "node": "route_user_intent",
    "stage": "route_generation_action",
    "description": "Route the user prompt to conversation handling or website generation.",
  },
  {
    "node": "prepare_multi_agent_context",
    "stage": "multi_agent_system",
    "description": "Prepare shared state, active agent, and routing-aware team context.",
  },
  {
    "node": "prepare_tool_contract",
    "stage": "gemini_tool_calling_setup",
    "description": "Prepare tool registry and expected tool-call order for the selected route.",
  },
  {
    "node": "prepare_adk_mapping",
    "stage": "google_adk_usage",
    "description": "Attach the Google ADK runtime plan and agent mapping.",
  },
  {
    "node": "execute_route_branch",
    "stage": "orchestration_flow",
    "description": "Execute either conversation handling or website artifact generation.",
  },
  {
    "node": "prepare_agent_handoff_contract",
    "stage": "agent_to_agent_communication",
    "description": "Record agent-to-agent message contract and handoff rules.",
  },
  {
    "node": "prepare_execution_summary",
    "stage": "proactive_thinking",
    "description": "Prepare assumptions, risks, next actions, and backend execution summary.",
  },
]
