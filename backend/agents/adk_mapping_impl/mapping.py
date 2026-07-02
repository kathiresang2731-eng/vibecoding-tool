from __future__ import annotations

from copy import deepcopy
from typing import Any

from .constants import ADK_AGENT_MAPPING, ADK_MAPPING_NOTES, ADK_RUNTIME_PLAN


def get_adk_mapping() -> dict[str, Any]:
  return {
    "summary": "Hybrid Google ADK mapping for the Worktual AI Dev prompt-to-website generation pipeline.",
    "adk_agents": deepcopy(ADK_AGENT_MAPPING),
    "runtime_plan": list(ADK_RUNTIME_PLAN),
    "notes": list(ADK_MAPPING_NOTES),
  }
