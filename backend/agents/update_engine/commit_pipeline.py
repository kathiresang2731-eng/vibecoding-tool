from __future__ import annotations

from typing import Any, Callable

from .contracts import CommitResult


ProgressCallback = Callable[..., None]


def filter_update_write_payload(
  *,
  files_before_map: dict[str, str],
  write_payload: list[dict[str, str]],
  prompt: str,
  intent: str,
  update_mode: str = "",
  request_kind: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
  if intent != "website_update":
    return write_payload, []
  try:
    from ..streaming.update_write_guard import filter_streaming_write_payload
  except ImportError:
    from agents.streaming.update_write_guard import filter_streaming_write_payload
  return filter_streaming_write_payload(
    files_before_map,
    write_payload,
    prompt=prompt,
    intent=intent,
    update_mode=update_mode or None,
    request_kind=request_kind or None,
  )


def _rejection_message(rejected_writes: list[dict[str, Any]], *, gate: str = "") -> str:
  for item in rejected_writes:
    if not isinstance(item, dict):
      continue
    reason = str(item.get("reason") or "")
    path = str(item.get("path") or "")
    if reason == "rewrite_exceeds_safe_fraction":
      fraction = item.get("change_fraction")
      allowed = item.get("allowed_fraction")
      pct = f"{float(fraction):.0%}" if isinstance(fraction, (int, float)) else "a large portion"
      limit = f"{float(allowed):.0%}" if isinstance(allowed, (int, float)) else "the safe limit"
      return (
        f"No code changes were saved. The edit to {path or 'the target file'} changed {pct} of the file "
        f"(limit {limit}). Retry with smaller color/className changes or ask to update a shared theme file."
      )
    if reason == "locked_platform_file":
      return (
        "No app code changes were saved. The agent tried to edit locked platform files "
        f"({path}). Retry and ask for changes in src/pages or src/components only."
      )
    if reason == "too_many_existing_files_changed":
      return "No code changes were saved. Too many files were modified in one update. Retry with a narrower request."
  if gate == "syntax":
    return (
      "The update edited files but saving was blocked by a syntax check (unbalanced braces or a missing export). "
      "Retry the same request — the agent will apply a smaller fix in the target page or component."
    )
  if gate == "precommit":
    return (
      "Build or visual QA blocked the save, so no code changes were committed. "
      "Your staged edits were not saved — retry or open Preview to verify."
    )
  return ""


def build_commit_user_message(
  *,
  saved_paths: list[str],
  rejected_writes: list[dict[str, Any]],
  agent_summary: str,
  scope_rationale: str = "",
  rejection_gate: str = "",
) -> str:
  if saved_paths:
    base = agent_summary.strip() or f"Updated {len(saved_paths)} file(s): {', '.join(saved_paths[:6])}."
    if scope_rationale.strip():
      return f"{base}\n\nScope: {scope_rationale[:320]}"
    return base[:500]

  rejection_message = _rejection_message(rejected_writes, gate=rejection_gate)
  if rejection_message:
    return rejection_message[:500]

  locked = [
    str(item.get("path") or "")
    for item in rejected_writes
    if isinstance(item, dict) and str(item.get("reason") or "") == "locked_platform_file"
  ]
  if locked:
    return (
      "No app code changes were saved. The agent tried to edit locked platform files "
      f"({', '.join(locked[:4])}). Retry and ask for changes in src/pages or src/components only."
    )
  if agent_summary.strip():
    return f"No code changes were saved. Agent summary: {agent_summary[:320]}"
  return (
    "I rebuilt the preview, but no code changes were applied. "
    "The update agent did not produce a safe file patch for this request."
  )


def commit_result_from_runtime(
  *,
  saved_paths: list[str],
  rejected_writes: list[dict[str, Any]],
  agent_summary: str,
  scope_rationale: str = "",
  preview_status: str = "skipped",
  rejection_gate: str = "",
) -> CommitResult:
  rejection_reason = _rejection_message(rejected_writes, gate=rejection_gate)
  return CommitResult(
    saved_paths=list(saved_paths),
    rejected_writes=list(rejected_writes),
    persisted=bool(saved_paths),
    user_message=build_commit_user_message(
      saved_paths=saved_paths,
      rejected_writes=rejected_writes,
      agent_summary=agent_summary,
      scope_rationale=scope_rationale,
      rejection_gate=rejection_gate,
    ),
    preview_status=preview_status,
    rejection_reason=rejection_reason,
    rejection_gate=rejection_gate,
  )
