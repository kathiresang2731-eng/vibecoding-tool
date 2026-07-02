from __future__ import annotations

from typing import Any, Callable

from ..runtime_config import patch_approval_enabled
from .presentation import patch_approval_conversation_response, public_patch_approval_brief
from .storage import load_pending_patch, patch_approval_store_ready, persist_pending_patch, resolve_pending_patch

try:
  from ..agent_runtime.progress import emit_runtime_progress
except ImportError:
  from agent_runtime.progress import emit_runtime_progress


ProgressCallback = Callable[..., None]


def patch_approval_active(tool_context: Any) -> bool:
  return patch_approval_enabled() and patch_approval_store_ready(tool_context)


def snapshot_from_runtime_state(state: dict[str, Any]) -> dict[str, Any]:
  candidate_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or item.get("code") or "")}
    for item in list(state.get("candidate_files") or [])
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  code_diff = state.get("code_diff_summary") if isinstance(state.get("code_diff_summary"), dict) else {}
  paths = [
    str(path).strip()
    for path in list(state.get("changed_file_paths") or state.get("patch_paths") or [])
    if str(path).strip()
  ]
  if not paths:
    paths = [item["path"] for item in candidate_files if item.get("path")]
  diff_detail = dict(code_diff)
  if candidate_files and not diff_detail.get("diffs"):
    diff_detail.setdefault("file_count", len(candidate_files))
    diff_detail.setdefault("paths", paths)
  return {
    "prompt": str(state.get("prompt") or ""),
    "operation": state.get("operation"),
    "paths": paths,
    "candidate_files": candidate_files,
    "patch_set": state.get("patch_set") if isinstance(state.get("patch_set"), dict) else {},
    "diff_detail": diff_detail,
  }


def emit_patch_approval_required(progress: ProgressCallback, pending: dict[str, Any]) -> None:
  diff_detail = pending.get("diff_detail") if isinstance(pending.get("diff_detail"), dict) else {}
  emit_runtime_progress(
    progress,
    "patch.approval.required",
    "Waiting for your approval before applying the proposed patch",
    status="running",
    detail={
      "paths": list(pending.get("paths") or []),
      "patch_approval": public_patch_approval_brief(pending),
      **({"diffs": diff_detail.get("diffs"), "file_count": diff_detail.get("file_count"), "added": diff_detail.get("added"), "removed": diff_detail.get("removed")} if diff_detail else {}),
    },
  )


def require_patch_approval_before_commit(
  state: dict[str, Any],
  *,
  tool_context: Any,
  user: Any,
  project_id: str,
  progress: ProgressCallback,
  patch_action: str | None = None,
) -> bool:
  """Return True when commit must pause for human patch approval."""
  if not patch_approval_active(tool_context):
    return False
  if patch_action == "approve" or state.get("patch_approval_granted"):
    state["patch_approval_granted"] = True
    return False

  snapshot = snapshot_from_runtime_state(state)
  if not snapshot.get("candidate_files"):
    return False

  pending = persist_pending_patch(tool_context, user, project_id=project_id, snapshot=snapshot)
  state["awaiting_patch_approval"] = True
  state["patch_approval"] = pending
  emit_patch_approval_required(progress, pending)
  return True


def finalize_awaiting_patch_approval_result(state: dict[str, Any], *, generated_website: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
  pending = state.get("patch_approval") if isinstance(state.get("patch_approval"), dict) else {}
  runtime = {
    **runtime,
    "status": "awaiting_patch_approval",
    "awaiting_patch_approval": True,
    "patch_approval": public_patch_approval_brief(pending),
  }
  return {
    "state": state,
    "artifact_response": state.get("artifact_response") if isinstance(state.get("artifact_response"), dict) else {},
    "generated_website": generated_website,
    "runtime": runtime,
    "local_sync": state.get("local_sync"),
    "preview": state.get("preview"),
    "awaiting_patch_approval": True,
    "patch_approval": pending,
  }


def resolve_patch_approval_turn(
  *,
  project_id: str,
  patch_action: str,
  context: Any,
  user: Any,
  progress_callback: ProgressCallback | None,
  prompt: str = "",
) -> dict[str, Any]:
  try:
    from ..agent_tools import ToolRuntimeContext
  except ImportError:
    from agent_tools import ToolRuntimeContext
  tool_context = ToolRuntimeContext(store=context.store, settings=context.settings)
  pending = load_pending_patch(tool_context, user, project_id=project_id)
  if not pending:
    raise ValueError("No pending patch is waiting for approval on this project.")

  progress = progress_callback or (lambda *_args, **_kwargs: None)
  if patch_action == "reject":
    resolve_pending_patch(tool_context, user, project_id=project_id, pending=pending, status="rejected")
    emit_runtime_progress(
      progress,
      "patch.approval.rejected",
      "Discarded the proposed patch without applying changes",
      status="completed",
      detail={"paths": list(pending.get("paths") or [])},
    )
    conversation = patch_approval_conversation_response(
      {**pending, "status": "rejected"},
      message="I discarded the proposed patch and did not change your project files.",
    )
    return _build_patch_action_payload(
      context=context,
      user=user,
      project_id=project_id,
      prompt=prompt or "Reject the proposed patch.",
      conversation=conversation,
      files=context.store.list_files(project_id, user),
    )

  candidate_files = [
    {"path": str(item.get("path") or ""), "code": str(item.get("content") or item.get("code") or "")}
    for item in list(pending.get("candidate_files") or [])
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  if not candidate_files:
    raise ValueError("Pending patch snapshot did not include any files to apply.")

  context.store.apply_generated_files(project_id, user, candidate_files)
  resolve_pending_patch(tool_context, user, project_id=project_id, pending=pending, status="approved")
  emit_runtime_progress(
    progress,
    "patch.applied",
    f"Applied approved patch to {len(candidate_files)} file(s)",
    status="completed",
    detail={"paths": [item["path"] for item in candidate_files], "file_count": len(candidate_files)},
  )
  diff_detail = pending.get("diff_detail") if isinstance(pending.get("diff_detail"), dict) else {}
  if diff_detail.get("diffs"):
    emit_runtime_progress(
      progress,
      "file.diff.ready",
      f"Applied approved patch: {diff_detail.get('file_count', len(candidate_files))} files",
      status="completed",
      detail=diff_detail,
    )

  conversation = {
    "type": "patch_applied",
    "message": f"Applied the approved patch to {len(candidate_files)} file(s).",
    "next_prompt_guidance": ["Review the updated files.", "Run preview.", "Ask for another change."],
    "patch_approval": public_patch_approval_brief({**pending, "status": "approved"}),
  }
  return _build_patch_action_payload(
    context=context,
    user=user,
    project_id=project_id,
    prompt=prompt or "Approve and apply the proposed patch.",
    conversation=conversation,
    files=context.store.list_files(project_id, user),
    applied_files=candidate_files,
  )


def _build_patch_action_payload(
  *,
  context: Any,
  user: Any,
  project_id: str,
  prompt: str,
  conversation: dict[str, Any],
  files: list[dict[str, Any]],
  applied_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  generation = {
    "multi_agent_system": {
      "intent": "website_update",
      "conversation_response": conversation,
      "agentic_runtime": {
        "status": conversation.get("patch_approval", {}).get("status", "completed"),
        "tool_source_of_truth": True,
      },
    },
    "orchestration_flow": {
      "generated_website": {
        "title": "Approved patch",
        "subheadline": prompt,
        "files": applied_files or [],
      },
    },
  }
  return {
    "generation": generation,
    "files": files,
    "patch_approval": conversation.get("patch_approval"),
  }
