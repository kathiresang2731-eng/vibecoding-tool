from __future__ import annotations

from typing import Any

from ...values import list_value, object_value, text_or_default


def latest_repair_error(state: dict[str, Any]) -> str | None:
  errors = state.get("repair_errors")
  if isinstance(errors, list) and errors:
    return str(errors[-1])
  return None


def compact_progress_reason(reason: str | None, *, max_length: int = 260) -> str:
  if not isinstance(reason, str):
    return ""
  compacted = " ".join(reason.split())
  if len(compacted) <= max_length:
    return compacted
  return f"{compacted[: max_length - 3]}..."


def public_supervisor_decision_detail(decision: dict[str, Any] | None) -> dict[str, Any]:
  if not isinstance(decision, dict):
    return {}
  return {
    "selected_agent": text_or_default(decision.get("next_agent"), ""),
    "selected_action": text_or_default(decision.get("next_action"), ""),
    "decision_source": text_or_default(decision.get("decision_source"), ""),
    "decision_reason": compact_progress_reason(text_or_default(decision.get("reason"), ""), max_length=320),
    "tools_to_call": list_value(decision.get("tools_to_call")),
  }


def action_progress_message(action: str, decision: dict[str, Any], state: dict[str, Any]) -> str:
  if action == "RUN_REPAIR_AGENT":
    reason = compact_progress_reason(latest_repair_error(state))
    if reason:
      return f"{decision['next_agent']} repairing generated files because: {reason}"
    return f"{decision['next_agent']} repairing generated files"
  if action == "RUN_UPDATE_ANALYST":
    return "Update Analysis Agent selecting the smallest safe existing-project update flow"
  if action == "RUN_SCOPED_UPDATE_AGENT":
    analysis = object_value(state.get("update_analysis"))
    mode = text_or_default(analysis.get("update_mode"), "scoped update").replace("_", " ")
    return f"Scoped Update Agent applying only the approved {mode} files"
  if action == "MATERIALIZE_CANDIDATE_FILES":
    return f"{decision['next_agent']} writing planned files to the workspace"
  return f"{decision['next_agent']} executing {action}"


def action_progress_detail(action: str, state: dict[str, Any], decision: dict[str, Any] | None = None) -> dict[str, Any] | None:
  detail = public_supervisor_decision_detail(decision)
  if action == "RUN_UPDATE_ANALYST":
    detail.update({"operation": "website_update", "skipped_dynamic_agents": True})
    return detail
  if action == "RUN_SCOPED_UPDATE_AGENT":
    analysis = object_value(state.get("update_analysis"))
    detail.update(
      {
        "update_mode": analysis.get("update_mode"),
        "request_kind": analysis.get("request_kind"),
        "execution_strategy": analysis.get("execution_strategy"),
        "candidate_files": analysis.get("candidate_files"),
        "candidate_new_files": analysis.get("candidate_new_files"),
        "repair_attempt": int(state.get("repair_attempts") or 0) + 1 if latest_repair_error(state) else 0,
      }
    )
    return detail
  if action != "RUN_REPAIR_AGENT":
    return detail or None
  reason = latest_repair_error(state)
  detail.update(
    {
      "repair_reason": reason,
      "repair_attempt": int(state.get("repair_attempts") or 0) + 1,
    }
  )
  return detail


def preview_build_failure_reason(build_log: Any) -> str:
  text = str(build_log or "").strip()
  if not text:
    return "Staged preview build failed before returning a build log."

  lower_text = text.lower()
  priority_markers = (
    "preview runtime scan failed:",
    "runtime scan failed:",
    "syntaxerror",
    "referenceerror",
    "module not found",
    "error:",
    "build failed",
  )
  for marker in priority_markers:
    index = lower_text.find(marker)
    if index != -1:
      return compact_progress_reason(text[index:], max_length=1200)

  if "✓ built" in text or "built in" in lower_text:
    return (
      "Staged preview did not become ready after a successful-looking Vite build. "
      "Check the preview runtime scan and project version status."
    )
  return compact_progress_reason(text, max_length=1200) or "Staged preview build failed."


def is_unsafe_bare_react_reason(reason: str) -> bool:
  lowered = str(reason or "").lower()
  return "unsafe bare react" in lowered or "generated jsx files must import react" in lowered


def is_missing_vite_entry_reason(reason: str) -> bool:
  lowered = str(reason or "").lower()
  return 'could not resolve entry module "index.html"' in lowered or "could not resolve entry module 'index.html'" in lowered
