from __future__ import annotations

from ..agent_tool_catalog import DEFAULT_AGENT_TEAM, DEFAULT_TOOL_REGISTRY
from ..schema import REQUIRED_RESPONSE_SECTIONS

PIPELINE_STAGE_ORDER = tuple(REQUIRED_RESPONSE_SECTIONS)
TOOL_LOG_MAX_CHARS = 2400

ROUTING_INTENT_CONFIG = {
  "greeting": {
    "next_action": "respond_and_collect_website_brief",
    "next_tool": "handle_greeting",
  },
  "question": {
    "next_action": "answer_question",
    "next_tool": "answer_question",
  },
  "general_query": {
    "next_action": "answer_general_query",
    "next_tool": "answer_general_query",
  },
  "web_search": {
    "next_action": "search_web",
    "next_tool": "search_web",
  },
  "needs_more_detail": {
    "next_action": "request_website_details",
    "next_tool": "request_website_details",
  },
  "project_info": {
    "next_action": "summarize_current_project",
    "next_tool": "summarize_current_project",
  },
  "simple_code": {
    "next_action": "write_standalone_code_file",
    "next_tool": "generate_simple_code_file",
  },
  "document_artifact": {
    "next_action": "write_document_artifact",
    "next_tool": "generate_document_artifact",
  },
  "needs_confirmation": {
    "next_action": "confirm_execution_brief",
    "next_tool": "confirm_execution_brief",
  },
  "website_generation": {
    "next_action": "generate_website",
    "next_tool": "analyze_prompt",
  },
  "website_update": {
    "next_action": "update_website",
    "next_tool": "analyze_update_request",
  },
}

__all__ = [
  "DEFAULT_AGENT_TEAM",
  "DEFAULT_TOOL_REGISTRY",
  "PIPELINE_STAGE_ORDER",
  "ROUTING_INTENT_CONFIG",
  "TOOL_LOG_MAX_CHARS",
]
