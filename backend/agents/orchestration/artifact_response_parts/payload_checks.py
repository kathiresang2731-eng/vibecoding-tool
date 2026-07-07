from __future__ import annotations

from typing import Any

_GENERIC_UPDATE_SUMMARIES = {
  "parallel file workers completed.",
  "updated project files from your prompt.",
}

_GENERIC_GENERATION_SUMMARIES = {
  "parallel file workers completed.",
  "generated project files from your prompt.",
  "streaming file agent finished",
}


def _non_empty_string_list(value: Any) -> list[str]:
  if not isinstance(value, list):
    return []
  return [str(item).strip() for item in value if str(item or "").strip()]


def _file_entry_paths(value: Any, *, changed_only: bool = False) -> list[str]:
  if not isinstance(value, list):
    return []
  paths: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    if not path:
      continue
    purpose = str(item.get("purpose") or "").strip().lower()
    if "preserved existing project file" in purpose:
      continue
    if changed_only:
      if purpose and any(marker in purpose for marker in ("updated", "changed", "generated", "created")):
        paths.append(path)
        continue
      if str(item.get("content") or item.get("code") or "").strip():
        paths.append(path)
      continue
    paths.append(path)
  return paths


def _payload_change_containers(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
  containers: list[dict[str, Any]] = [artifact_response]
  for key in ("targeted_update", "scoped_update", "update_result", "runtime", "agentic_runtime", "final_output"):
    value = artifact_response.get(key)
    if isinstance(value, dict):
      containers.append(value)

  artifact_generated = artifact_response.get("generated_website")
  if isinstance(artifact_generated, dict):
    containers.append(artifact_generated)
  if isinstance(generated_website, dict):
    containers.append(generated_website)
  return containers


def _payload_has_code_change_evidence(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> bool:
  if not isinstance(artifact_response, dict):
    return False

  for container in _payload_change_containers(artifact_response, generated_website):
    for key in ("changed_file_paths", "changed_paths", "patch_paths", "materialized_file_paths"):
      if _non_empty_string_list(container.get(key)):
        return True
    if _file_entry_paths(container.get("changed_files")):
      return True

    files = container.get("files")
    if container is artifact_response:
      if _file_entry_paths(files):
        return True
    elif _file_entry_paths(files, changed_only=True):
      return True

    diff_summary = container.get("code_diff_summary")
    if isinstance(diff_summary, dict):
      try:
        if int(diff_summary.get("file_count") or 0) > 0:
          return True
      except (TypeError, ValueError):
        pass

    diff_detail = container.get("diff_detail")
    if isinstance(diff_detail, dict) and isinstance(diff_detail.get("diffs"), list) and diff_detail.get("diffs"):
      return True

  return False


def _payload_explicitly_has_no_code_changes(
  artifact_response: dict[str, Any],
  generated_website: dict[str, Any] | None = None,
) -> bool:
  if not isinstance(artifact_response, dict):
    return False
  if _payload_has_code_change_evidence(artifact_response, generated_website):
    return False

  for container in _payload_change_containers(artifact_response, generated_website):
    saw_change_path_field = False
    for key in ("changed_file_paths", "changed_paths"):
      if key not in container:
        continue
      saw_change_path_field = True
    if saw_change_path_field:
      return True

  if "files" in artifact_response and isinstance(artifact_response.get("files"), list):
    return not _file_entry_paths(artifact_response.get("files"))

  return False
