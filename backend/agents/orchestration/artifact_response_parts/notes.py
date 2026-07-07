from __future__ import annotations

from typing import Any


def normalize_string_list(value: Any, fallback: list[str]) -> list[str]:
  if isinstance(value, list):
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if normalized:
      return normalized
  return fallback


def extract_implementation_notes(response: dict[str, Any]) -> dict[str, Any]:
  notes = response.get("implementation_notes")
  if isinstance(notes, dict):
    return notes

  proactive_thinking = response.get("proactive_thinking")
  if isinstance(proactive_thinking, dict):
    return proactive_thinking

  return {}


def list_from_notes(notes: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
  return normalize_string_list(notes.get(key), fallback)
