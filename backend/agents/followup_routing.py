from __future__ import annotations

from typing import Any

from .project_workspace import is_standalone_code_project, is_vite_scaffold_complete, meaningful_project_source_files
from .prompt_context import current_user_prompt
from .streaming.task_planner import (
  is_explicit_greenfield_website_request,
  is_requirement_rebuild_request,
  is_rich_greenfield_website_request,
)

EXPLICIT_NEW_PROJECT_MARKERS = (
  "new website",
  "new site",
  "from scratch",
  "start over",
  "start fresh",
  "another website",
  "different website",
  "rebuild the whole",
  "rebuild entire",
  "brand new site",
)

EXPLICIT_WEB_PROJECT_MARKERS = (
  "website",
  "web site",
  "web app",
  "site",
  "landing page",
  "frontend",
  "front end",
  "ui page",
  "dashboard",
  "react",
  "vite",
)


def _routing_result_for_intent(intent: str, reason: str) -> dict[str, str]:
  if intent == "website_update":
    return {
      "intent": "website_update",
      "next_action": "update_website",
      "next_tool": "analyze_update_request",
      "reason": reason,
    }
  if intent == "simple_code":
    return {
      "intent": "simple_code",
      "next_action": "write_standalone_code_file",
      "next_tool": "generate_simple_code_file",
      "reason": reason,
    }
  raise ValueError(f"Unsupported follow-up routing intent: {intent}")


def is_explicit_new_project_request(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  if not lowered:
    return False
  return any(marker in lowered for marker in EXPLICIT_NEW_PROJECT_MARKERS)


def is_explicit_web_project_request(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  if not lowered:
    return False
  return any(marker in lowered for marker in EXPLICIT_WEB_PROJECT_MARKERS)


def is_broad_website_generation_requirement(prompt: str) -> bool:
  lowered = current_user_prompt(prompt).strip().lower()
  if not lowered:
    return False
  if is_requirement_rebuild_request(lowered):
    return True
  return is_explicit_greenfield_website_request(lowered) and is_rich_greenfield_website_request(lowered)


def apply_existing_project_routing_bias(
  routing_result: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]] | None,
) -> dict[str, Any]:
  """When a live codebase already exists, follow-up turns should update — not re-brief or regenerate."""
  if not isinstance(routing_result, dict):
    return routing_result
  intent = str(routing_result.get("intent") or "").strip()
  user_prompt = current_user_prompt(prompt).strip()
  if is_standalone_code_project(project_files) and not is_explicit_web_project_request(user_prompt):
    if intent in {"website_generation", "website_update", "needs_more_detail"}:
      return _routing_result_for_intent(
        "simple_code",
        "Existing project contains standalone code only; treating this follow-up as a code-only update.",
      )
    return routing_result
  if not meaningful_project_source_files(project_files):
    return routing_result
  if not is_vite_scaffold_complete(project_files):
    return routing_result

  if not user_prompt or intent not in {"website_generation", "needs_more_detail"}:
    return routing_result
  understanding = routing_result.get("request_understanding")
  if (
    intent == "needs_more_detail"
    and isinstance(understanding, dict)
    and understanding.get("clarification_required") is True
  ):
    return routing_result

  if is_broad_website_generation_requirement(user_prompt):
    if intent == "needs_more_detail":
      return {
        "intent": "website_generation",
        "next_action": "generate_website",
        "next_tool": "analyze_prompt",
        "reason": "Detailed website requirements were provided; using full generation instead of scoped update.",
      }
    if intent == "website_generation":
      return routing_result

  if intent == "needs_more_detail":
    return _routing_result_for_intent(
      "website_update",
      "Existing project files are loaded; treating this follow-up as a scoped website update.",
    )

  if intent == "website_generation" and not is_explicit_new_project_request(user_prompt):
    if is_broad_website_generation_requirement(user_prompt) or is_requirement_rebuild_request(user_prompt):
      return routing_result
    return _routing_result_for_intent(
      "website_update",
      "Existing project files are loaded; treating this request as an update to the current website.",
    )

  return routing_result
