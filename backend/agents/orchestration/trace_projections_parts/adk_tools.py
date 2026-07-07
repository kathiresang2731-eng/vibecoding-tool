from __future__ import annotations

from typing import Any

from .common import LOCAL_ADK_TOOL_SPECS


def _build_adk_tool_specs() -> list[dict[str, Any]]:
  tools = [dict(tool) for tool in LOCAL_ADK_TOOL_SPECS]
  try:
    from backend.agent_tools import website_tool_schemas
  except ImportError:
    from ...tools import website_tool_schemas
  for schema in website_tool_schemas():
    tools.append(
      {
        "name": schema["name"],
        "description": schema.get("description", ""),
        "parameters": schema.get("parameters", {}),
        "adk_binding": {"type": "FunctionTool", "execution": "backend_tool_registry"},
      }
    )
  return tools


def build_adk_tool_specs() -> list[dict[str, Any]]:
  return _build_adk_tool_specs()
