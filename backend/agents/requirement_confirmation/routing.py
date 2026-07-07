from __future__ import annotations

from typing import Any


def _coerce_operation_for_project(
  operation: str,
  *,
  project_files: list[dict[str, Any]] | None,
  pending: dict[str, Any] | None = None,
) -> str:
  try:
    from ..followup_routing import is_explicit_web_project_request
    from ..project_workspace import is_standalone_code_project
  except ImportError:
    from agents.followup_routing import is_explicit_web_project_request
    from agents.project_workspace import is_standalone_code_project
  pending_text = ""
  if isinstance(pending, dict):
    pending_text = " ".join(
      [
        str(pending.get("summary") or ""),
        " ".join(str(item or "") for item in (pending.get("planned_changes") or []) if isinstance(item, str)),
        str(pending.get("effective_request") or pending.get("original_request") or ""),
      ]
    )
  if is_standalone_code_project(project_files) and not is_explicit_web_project_request(pending_text):
    return "simple_code"
  if operation != "website_update":
    return operation
  return operation


def confirmed_routing_result(
  pending: dict[str, Any],
  *,
  project_files: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
  operation = _coerce_operation_for_project(
    str(pending.get("operation") or "website_generation"),
    project_files=project_files,
    pending=pending,
  )
  if operation == "simple_code":
    return {
      "intent": "simple_code",
      "next_action": "write_standalone_code_file",
      "next_tool": "generate_simple_code_file",
      "reason": "The user confirmed a standalone code execution brief; keeping the project code-only.",
    }
  if operation == "website_update":
    return {
      "intent": "website_update",
      "next_action": "update_website",
      "next_tool": "analyze_update_request",
      "reason": "The user confirmed the persisted website update execution brief.",
    }
  return {
    "intent": "website_generation",
    "next_action": "generate_website",
    "next_tool": "analyze_prompt",
    "reason": "The user confirmed the persisted website generation execution brief.",
  }


def confirmation_routing_result(reason: str) -> dict[str, str]:
  return {
    "intent": "needs_confirmation",
    "next_action": "confirm_execution_brief",
    "next_tool": "confirm_execution_brief",
    "reason": reason,
  }


def revised_request(pending: dict[str, Any], user_message: str, decision: dict[str, str]) -> str:
  revision = decision.get("revision") or user_message.strip()
  return f"{pending.get('effective_request') or pending.get('original_request') or ''}\n\nUser revision:\n{revision}".strip()
