from __future__ import annotations

from typing import Any

from .payload_checks import (
  _GENERIC_GENERATION_SUMMARIES,
  _GENERIC_UPDATE_SUMMARIES,
  _file_entry_paths,
  _payload_explicitly_has_no_code_changes,
  _payload_has_code_change_evidence,
)


def build_update_conversation_message(
  *,
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> str:
  summary = str(artifact_response.get("summary") or artifact_response.get("output_text") or "").strip()
  generic_summary = summary.lower() in _GENERIC_UPDATE_SUMMARIES
  validation = artifact_response.get("update_validation") if isinstance(artifact_response, dict) else None
  if isinstance(validation, dict) and validation.get("kind") == "brand_rename":
    expected = str(validation.get("expected") or "the requested name")
    if validation.get("applied"):
      return f"Updated the website name to {expected}."
    if summary and not generic_summary and _payload_has_code_change_evidence(artifact_response, generated_website):  # type: ignore[name-defined]
      return summary[:400]
    return (
      f"The website name was not changed to {expected}. "
      "The agent explored files but did not update index.html or the navbar brand text."
    )
  clarification = str(artifact_response.get("clarification_question") or "").strip()
  if clarification:
    return clarification[:400]
  commit_result = artifact_response.get("commit_result")
  if not isinstance(commit_result, dict):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    if isinstance(runtime.get("commit_result"), dict):
      commit_result = runtime["commit_result"]
  if isinstance(commit_result, dict):
    commit_message = str(commit_result.get("user_message") or "").strip()
    if commit_message and (
      commit_result.get("persisted")
      or _payload_explicitly_has_no_code_changes(artifact_response, generated_website)
    ):
      return commit_message[:500]
  if _payload_explicitly_has_no_code_changes(artifact_response, generated_website):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    if not runtime and isinstance(artifact_response.get("agentic_runtime"), dict):
      runtime = artifact_response["agentic_runtime"]
    tool_failures = [str(item) for item in (runtime.get("tool_failures") or []) if str(item or "").strip()]
    rejected_writes = runtime.get("rejected_writes") if isinstance(runtime.get("rejected_writes"), list) else []
    locked_rejected = [
      str(item.get("path") or "")
      for item in rejected_writes
      if isinstance(item, dict) and str(item.get("reason") or "") == "locked_platform_file"
    ]
    if locked_rejected:
      return (
        "No app code changes were saved. The agent tried to edit locked platform files "
        f"({', '.join(locked_rejected[:4])}). Retry and ask for changes in src/pages or src/components only."
      )
    if any("syntax" in item.lower() for item in tool_failures):
      return (
        "The update edited files but saving was blocked by a syntax check (unbalanced braces or a missing export). "
        "Retry the same request — the agent will apply a smaller fix in the target page or component."
      )
    if summary and not generic_summary:
      return "No code changes were applied. " f"The update agent summary was: {summary[:320]}"
    return (
      "I rebuilt the preview, but no code changes were applied. "
      "The update agent did not produce a safe file patch for this request."
    )
  if summary and not generic_summary:
    return summary[:400]
  return "Updated the website preview from the provided prompt."


def build_generation_conversation_message(
  *,
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> str:
  clarification = str(artifact_response.get("clarification_question") or "").strip()
  if clarification:
    return clarification[:400]

  runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
  if str(runtime.get("status") or artifact_response.get("status") or "") == "needs_clarification":
    question = str(runtime.get("clarification_question") or artifact_response.get("summary") or "").strip()
    if question:
      return question[:400]

  summary = str(artifact_response.get("summary") or artifact_response.get("output_text") or runtime.get("output_text") or "").strip()
  generic_summary = summary.lower() in _GENERIC_GENERATION_SUMMARIES

  if _payload_explicitly_has_no_code_changes(artifact_response, generated_website):
    runtime = artifact_response.get("runtime") if isinstance(artifact_response.get("runtime"), dict) else {}
    tool_failures = [str(item) for item in (runtime.get("tool_failures") or []) if str(item or "").strip()]
    if any("syntax" in item.lower() for item in tool_failures):
      return (
        "The update edited files but saving was blocked by a syntax check (unbalanced braces or a missing export). "
        "Retry the same request — the agent will apply a smaller routing fix in src/App.jsx and related auth pages."
      )
    if isinstance(generated_website, dict):
      generated_file_count = len(_file_entry_paths(generated_website.get("files")))
      if generated_file_count:
        return f"Generated the website with {generated_file_count} file(s)."
    if summary and not generic_summary:
      return "No website files were generated. " f"The generation summary was: {summary[:320]}"
    return (
      "I prepared the preview shell, but no website files were generated for this request. "
      "Try adding more detail about pages, modules, and features you need."
    )

  changed_paths = []
  if isinstance(artifact_response.get("changed_paths"), list):
    changed_paths = [str(item).strip() for item in artifact_response["changed_paths"] if str(item or "").strip()]
  if not changed_paths:
    for container in (artifact_response, generated_website or {}):
      if isinstance(container, dict) and isinstance(container.get("changed_paths"), list):
        changed_paths = [str(item).strip() for item in container["changed_paths"] if str(item or "").strip()]
        if changed_paths:
          break

  files = generated_website.get("files") if isinstance(generated_website, dict) else []
  file_count = len(_file_entry_paths(files)) if isinstance(files, list) else len(changed_paths)
  if changed_paths:
    return f"Generated the website with {len(changed_paths)} updated file(s)."
  if file_count:
    return f"Generated the website with {file_count} file(s)."

  if summary and not generic_summary:
    return summary[:400]

  return "Generated the website preview from the provided prompt."
