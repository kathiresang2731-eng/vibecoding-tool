from __future__ import annotations

import json
import time
from typing import Any, Callable

try:
  from ....code_diff import build_project_diff, redact_project_diff_for_audit
except ImportError:
  from code_diff import build_project_diff, redact_project_diff_for_audit

from ...artifacts import normalize_generated_file_code
from ..errors import AgentRuntimeLoopError
from ..file_ops import project_files_to_tool_files, tool_files_to_artifact_files
from ..values import list_value, object_value, text_or_default


AgentProgressCallback = Callable[..., None]


def latest_repair_error(state: dict[str, Any]) -> str | None:
  errors = state.get("repair_errors")
  if isinstance(errors, list) and errors:
    return str(errors[-1])
  return None


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


def compact_progress_reason(reason: str | None, *, max_length: int = 260) -> str:
  if not isinstance(reason, str):
    return ""
  compacted = " ".join(reason.split())
  if len(compacted) <= max_length:
    return compacted
  return f"{compacted[: max_length - 3]}..."


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


def normalize_candidate_react_imports(files: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[str]]:
  normalized_files: list[dict[str, str]] = []
  changed_paths: list[str] = []
  for file_item in files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    normalized_content = normalize_generated_file_code(path, content)
    if normalized_content != content:
      changed_paths.append(path)
    normalized_files.append({"path": path, "content": normalized_content})
  return normalized_files, changed_paths


def sync_generated_website_files_from_candidates(state: dict[str, Any]) -> None:
  generated_website = object_value(state.get("generated_website"))
  candidate_files = list(state.get("candidate_files") or [])
  changed_paths = [file_item["path"] for file_item in candidate_files if isinstance(file_item, dict) and file_item.get("path")]
  if generated_website:
    generated_website["files"] = tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_paths)
    state["generated_website"] = generated_website
    state["files"] = generated_website["files"]



def workflow_progress_detail(workflow_plan: dict[str, Any]) -> dict[str, Any]:
  tasks = [
    {
      "id": text_or_default(task.get("id"), ""),
      "name": text_or_default(task.get("name"), text_or_default(task.get("id"), "Task")),
      "capability": text_or_default(task.get("required_capability"), ""),
      "phase": text_or_default(task.get("execution_phase"), ""),
      "risk": text_or_default(task.get("risk_level"), ""),
      "agent": text_or_default(task.get("agent_id"), ""),
    }
    for task in list_value(workflow_plan.get("tasks"))
    if isinstance(task, dict)
  ]
  assignments = [
    {
      "task_id": text_or_default(item.get("task_id"), ""),
      "agent_id": text_or_default(item.get("agent_id"), ""),
      "reused": bool(item.get("reused")),
      "created": bool(item.get("created")),
      "confidence": item.get("confidence"),
      "reason": text_or_default(item.get("reason"), ""),
    }
    for item in list_value(workflow_plan.get("assignments"))
    if isinstance(item, dict)
  ]
  return {
    "kind": "workflow_plan",
    "domain": workflow_plan.get("domain"),
    "scope": workflow_plan.get("scope"),
    "task_count": len(tasks),
    "active_agent_count": len(list_value(workflow_plan.get("active_agents"))),
    "created_agent_ids": list_value(workflow_plan.get("created_agent_ids")),
    "reused_agent_ids": list_value(workflow_plan.get("reused_agent_ids")),
    "parallel_groups": list_value(workflow_plan.get("parallel_groups")),
    "tasks": tasks[:16],
    "assignments": assignments[:16],
  }


def website_plan_progress_detail(plan: dict[str, Any], workflow_plan: dict[str, Any] | None = None) -> dict[str, Any]:
  sections = [str(item) for item in list_value(plan.get("sections")) if str(item).strip()]
  quality_checks = [str(item) for item in list_value(plan.get("quality_checks")) if str(item).strip()]
  files_to_change = [str(item) for item in list_value(plan.get("files_to_change")) if str(item).strip()]
  detail = {
    "kind": "website_plan",
    "operation": plan.get("operation"),
    "layout_strategy": plan.get("layout_strategy"),
    "update_strategy": plan.get("update_strategy"),
    "sections": sections[:12],
    "quality_checks": quality_checks[:12],
    "files_to_change": files_to_change[:12],
  }
  if workflow_plan:
    detail["workflow"] = workflow_progress_detail(workflow_plan)
  return detail


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


def   emit_candidate_code_diff_progress(
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


def completion_status(state: dict[str, Any]) -> dict[str, Any]:
  preview_status = object_value(state.get("preview")).get("status")
  return {
    "files_exist": bool(state.get("files")),
    "artifact_valid": object_value(state.get("validation_result")).get("status") == "valid",
    "staged_preview_ready": preview_status == "ready",
    "visual_qa_passed": object_value(state.get("visual_qa_result")).get("status") == "passed",
    "files_committed": bool(state.get("committed")),
    "memory_prepared": bool(state.get("memory")),
  }


def completion_proof(state: dict[str, Any]) -> bool:
  status = completion_status(state)
  return all(status.values())


def enforce_loop_budget(
  state: dict[str, Any],
  *,
  start_time: float,
  timeout_seconds: int,
  max_tool_calls: int,
) -> None:
  if time.monotonic() - start_time > timeout_seconds:
    if can_continue_after_timeout_for_finalization(state):
      state["runtime_budget_finalization_grace_used"] = True
      return
    raise AgentRuntimeLoopError(f"Agent runtime exceeded timeout budget of {timeout_seconds}s.")
  if len(state.get("tool_calls") or []) > max_tool_calls:
    raise AgentRuntimeLoopError(f"Agent runtime exceeded tool-call budget of {max_tool_calls}.")


def can_continue_after_timeout_for_finalization(state: dict[str, Any]) -> bool:
  status = completion_status(state)
  expensive_work_done = (
    status["files_exist"]
    and status["artifact_valid"]
    and status["staged_preview_ready"]
    and status["visual_qa_passed"]
  )
  if not expensive_work_done:
    return False
  return not state.get("completed")
