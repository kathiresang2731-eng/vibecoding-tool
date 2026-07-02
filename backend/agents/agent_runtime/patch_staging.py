from __future__ import annotations

from typing import Any

try:
  from ...execution.patch import PatchEngineError, apply_patches_to_files
  from ...execution.patch.diff_builder import build_unified_patches_from_file_changes
except ImportError:
  from execution.patch import PatchEngineError, apply_patches_to_files
  from execution.patch.diff_builder import build_unified_patches_from_file_changes

from .errors import AgentRuntimeLoopError
from .progress import emit_patch_proposed_progress
from .tooling import execute_tool_call
from .values import list_value


def stage_candidate_patches_via_apply_patch(
  state: dict[str, Any],
  *,
  existing_files: list[dict[str, str]],
  changed_files: list[dict[str, str]],
  tool_executor: Any,
  tool_context: Any,
  user: Any,
  project_id: str,
  agent: str,
  progress: Any,
  stage: str = "scoped_update_staged",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
  """Stage scoped edits through APPLY_PATCH when possible; fall back to in-process apply."""
  patches = build_unified_patches_from_file_changes(existing_files, changed_files)
  if not patches:
    return changed_files, {}

  arguments = {"project_id": project_id, "patches": patches}
  patch_result: dict[str, Any]
  try:
    patch_result = execute_tool_call(
      state,
      tool_executor=tool_executor,
      tool_context=tool_context,
      user=user,
      agent=agent,
      name="APPLY_PATCH",
      arguments=arguments,
    )
  except AgentRuntimeLoopError as exc:
    error_text = str(exc)
    if "APPLY_PATCH" not in error_text:
      raise
    try:
      merged_files, summary = apply_patches_to_files(existing_files, patches)
    except PatchEngineError as patch_exc:
      raise AgentRuntimeLoopError(f"Scoped update patch staging failed: {patch_exc}") from patch_exc
    patch_result = {
      "project_id": project_id,
      "status": "staged",
      "patch_set": summary,
      "files": merged_files,
      "staged_locally": True,
    }

  patch_set = patch_result.get("patch_set") if isinstance(patch_result.get("patch_set"), dict) else {}
  staged_files = patch_result.get("files") if isinstance(patch_result.get("files"), list) else changed_files
  staged_tool_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in staged_files
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  ]
  if not staged_tool_files:
    staged_tool_files = changed_files

  state["patch_set"] = patch_set
  state["patch_staged"] = True
  state["patch_paths"] = list_value((patch_set.get("diff_stats") or {}).get("paths"))
  emit_patch_proposed_progress(
    state,
    progress,
    stage=stage,
    patch_set=patch_set,
    message_prefix="Patch proposed for review",
  )
  return staged_tool_files, patch_set
