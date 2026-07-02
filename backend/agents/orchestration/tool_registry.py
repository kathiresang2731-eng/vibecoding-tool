from __future__ import annotations

import json
from typing import Any

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from .constants import TOOL_LOG_MAX_CHARS

try:
  from ..agent_tool_catalog import REAL_BACKEND_TOOL_REGISTRY_ENTRIES
except ImportError:
  from agents.agent_tool_catalog import REAL_BACKEND_TOOL_REGISTRY_ENTRIES


def merge_tool_registry_entries(existing: Any, additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
  merged = [item for item in existing if isinstance(item, dict)]
  names = {item.get("name") for item in merged}
  for item in additions:
    if item["name"] not in names:
      merged.append(item)
      names.add(item["name"])
  return merged

def real_backend_tool_registry_entries() -> list[dict[str, Any]]:
  return [dict(item) for item in REAL_BACKEND_TOOL_REGISTRY_ENTRIES]

def merge_agents(required_agents: list[dict[str, Any]], response_agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
  merged: list[dict[str, Any]] = []
  seen_names: set[str] = set()
  for agent in [*required_agents, *response_agents]:
    name = str(agent.get("name") or "").strip()
    key = name.lower()
    if not name or key in seen_names:
      continue
    seen_names.add(key)
    merged.append(agent)
  return merged

def merge_tools(required_tools: list[dict[str, Any]], response_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
  merged: list[dict[str, Any]] = []
  seen_names: set[str] = set()
  for tool in [*required_tools, *response_tools]:
    name = str(tool.get("name") or "").strip()
    key = name.lower()
    if not name or key in seen_names:
      continue
    seen_names.add(key)
    merged.append(tool)
  return merged

def merge_tool_sequence(required_sequence: list[str], response_sequence: list[str]) -> list[str]:
  merged: list[str] = []
  for name in [*required_sequence, *response_sequence]:
    if isinstance(name, str) and name and name not in merged:
      merged.append(name)
  return merged

def log_tool_call(tool_name: str, phase: str, payload: Any) -> None:
  try:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
  except TypeError:
    serialized = str(payload)

  if len(serialized) > TOOL_LOG_MAX_CHARS:
    serialized = f"{serialized[:TOOL_LOG_MAX_CHARS]}... <truncated>"

  log_query_event(
    f"tool_route.{phase}",
    status="failed" if "fail" in phase else "completed",
    payload={"tool_name": tool_name, "phase": phase, "payload": payload},
  )
  print(f"[WorktualToolCall] {tool_name}.{phase}: {serialized}", flush=True)
