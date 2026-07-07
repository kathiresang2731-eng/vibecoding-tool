from __future__ import annotations

from typing import Any

from .catalog import real_backend_tool_registry_entries


def merge_tool_registry_entries(existing: Any, additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
  merged = [item for item in existing if isinstance(item, dict)]
  names = {item.get("name") for item in merged}
  for item in additions:
    if item["name"] not in names:
      merged.append(item)
      names.add(item["name"])
  return merged


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
