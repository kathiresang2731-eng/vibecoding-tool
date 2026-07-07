from __future__ import annotations

from typing import Any

try:
  from ...agent_tool_catalog import REAL_BACKEND_TOOL_REGISTRY_ENTRIES
except ImportError:
  from agents.agent_tool_catalog import REAL_BACKEND_TOOL_REGISTRY_ENTRIES


def real_backend_tool_registry_entries() -> list[dict[str, Any]]:
  return [dict(item) for item in REAL_BACKEND_TOOL_REGISTRY_ENTRIES]
