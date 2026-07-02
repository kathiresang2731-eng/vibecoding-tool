from __future__ import annotations

from typing import Any


def default_plan(operation: str) -> list[str]:
  if operation == "website_update":
    return [
      "Inspect the existing project and identify the smallest safe change scope.",
      "Apply only the approved changes while preserving unrelated code and UI.",
      "Validate, build, and run runtime QA before committing files.",
    ]
  return [
    "Analyze the confirmed website brief and required domain workflows.",
    "Generate the complete project structure and implementation.",
    "Validate, build, and run runtime QA before committing files.",
  ]


def string_list(value: Any, *, limit: int) -> list[str]:
  if not isinstance(value, list):
    return []
  result: list[str] = []
  for item in value:
    if isinstance(item, str) and item.strip():
      result.append(item.strip())
    if len(result) >= limit:
      break
  return result


def text(value: Any, fallback: str) -> str:
  return value.strip() if isinstance(value, str) and value.strip() else fallback


def normalize_enum(value: Any, allowed: set[str], fallback: str) -> str:
  normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
  return normalized if normalized in allowed else fallback
