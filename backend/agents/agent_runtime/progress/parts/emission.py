from __future__ import annotations

import json
from typing import Any, Callable

try:
  from backend.code_diff import build_project_diff, redact_project_diff_for_audit
except ImportError:
  from code_diff import build_project_diff, redact_project_diff_for_audit

from ...file_ops import project_files_to_tool_files
from ...values import list_value, object_value


AgentProgressCallback = Callable[..., None]


def emit_runtime_progress(progress: AgentProgressCallback, step: str, message: str, **kwargs: Any) -> None:
  compact_kwargs = {key: value for key, value in kwargs.items() if value is not None}
  try:
    progress(step, message, **compact_kwargs)
  except TypeError:
    progress(step, message)


def code_diff_progress_signature(diff_payload: dict[str, Any]) -> str:
  files = [
    {
      "path": item.get("path"),
      "status": item.get("status"),
      "added": item.get("added"),
      "removed": item.get("removed"),
      "old_hash": item.get("old_hash"),
      "new_hash": item.get("new_hash"),
    }
    for item in list_value(diff_payload.get("diffs"))
    if isinstance(item, dict)
  ]
  signature_payload = {
    "file_count": diff_payload.get("file_count", 0),
    "added": diff_payload.get("added", 0),
    "removed": diff_payload.get("removed", 0),
    "truncated_files": diff_payload.get("truncated_files", 0),
    "files": files,
  }
  return json.dumps(signature_payload, sort_keys=True, ensure_ascii=True)


def emit_gate_progress(
  progress: AgentProgressCallback,
  *,
  gate: str,
  phase: str,
  message: str,
  detail: dict[str, Any] | None = None,
) -> None:
  step = {"started": "gate.started", "passed": "gate.passed", "failed": "gate.failed"}.get(phase, "gate.started")
  status = "failed" if phase == "failed" else ("completed" if phase == "passed" else "running")
  payload = {"gate": gate, **(detail or {})}
  emit_runtime_progress(progress, step, message, status=status, detail=payload)


def emit_patch_proposed_progress(
  state: dict[str, Any],
  progress: AgentProgressCallback,
  *,
  stage: str,
  patch_set: dict[str, Any] | None = None,
  message_prefix: str = "Patch proposed",
) -> None:
  diff_stats = patch_set.get("diff_stats") if isinstance(patch_set, dict) else {}
  if not isinstance(diff_stats, dict):
    diff_stats = {}
  paths = [
    str(path).strip()
    for path in list_value(diff_stats.get("paths"))
    if str(path).strip()
  ]
  if not paths:
    paths = [
      str(path).strip()
      for path in list_value(state.get("changed_file_paths"))
      if str(path).strip()
  ]
  detail: dict[str, Any] = {
    "stage": stage,
    "paths": paths,
    "diff_stats": diff_stats,
    "patch_set": patch_set or {},
  }
  code_diff = state.get("code_diff_summary")
  if isinstance(code_diff, dict) and code_diff:
    detail["code_diff_summary"] = code_diff
  emit_runtime_progress(
    progress,
    "patch.proposed",
    f"{message_prefix}: {len(paths)} file(s)",
    status="running",
    detail=detail,
  )


def emit_patch_applied_progress(
  state: dict[str, Any],
  progress: AgentProgressCallback,
  *,
  file_count: int,
  message_prefix: str = "Patch applied",
) -> None:
  patch_set = state.get("patch_set") if isinstance(state.get("patch_set"), dict) else {}
  paths = [
    str(path).strip()
    for path in list_value(state.get("changed_file_paths") or state.get("patch_paths"))
    if str(path).strip()
  ]
  detail = {
    "paths": paths,
    "file_count": file_count,
    "patch_set": patch_set,
    "stage": "committed",
  }
  emit_runtime_progress(
    progress,
    "patch.applied",
    f"{message_prefix}: {file_count} file(s)",
    status="completed",
    detail=detail,
  )


def emit_candidate_code_diff_progress(
  state: dict[str, Any],
  progress: AgentProgressCallback,
  *,
  stage: str,
  message_prefix: str = "Prepared code changes",
) -> dict[str, Any]:
  read_files = object_value(state.get("read_result")).get("files")
  candidate_files = list(state.get("candidate_files") or [])
  if not isinstance(read_files, list) or not candidate_files:
    return {}
  existing_files = project_files_to_tool_files(read_files)

  compare_mode = "changed_only" if len(candidate_files) < len(existing_files) else "all"
  diff_payload = build_project_diff(existing_files, candidate_files, compare_mode=compare_mode)
  diff_summary = redact_project_diff_for_audit(diff_payload)
  state["code_diff_summary"] = diff_summary
  if not diff_payload.get("file_count"):
    return diff_payload

  signature = code_diff_progress_signature(diff_payload)
  if signature == state.get("_last_code_diff_signature"):
    return diff_payload
  state["_last_code_diff_signature"] = signature

  detail = {**diff_payload, "stage": stage}
  audit_detail = {**diff_summary, "stage": stage}
  patch_set = {
    "diff_stats": {
      "paths": [item.get("path") for item in list_value(diff_payload.get("diffs")) if isinstance(item, dict)],
      "additions": diff_payload.get("added", 0),
      "deletions": diff_payload.get("removed", 0),
    }
  }
  if stage in {"code_candidate_prepared", "repair_candidate_prepared"}:
    emit_patch_proposed_progress(
      state,
      progress,
      stage=stage,
      patch_set=patch_set,
      message_prefix=message_prefix,
    )
  emit_runtime_progress(
    progress,
    "file.diff.ready",
    f"{message_prefix}: {diff_payload.get('file_count', 0)} files, +{diff_payload.get('added', 0)} / -{diff_payload.get('removed', 0)}",
    status="completed",
    detail=detail,
    audit_detail=audit_detail,
  )
  return diff_payload
