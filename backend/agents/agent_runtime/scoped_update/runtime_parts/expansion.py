from __future__ import annotations

from typing import Any

from backend.agents.artifacts import normalize_artifact_path
from backend.agents.agent_runtime.constants import SCOPED_UPDATE_MAX_EXISTING_FILES, SCOPED_UPDATE_MAX_SCOPE_EXPANSIONS
from backend.agents.agent_runtime.errors import ScopedUpdateGuardError
from backend.agents.agent_runtime.file_ops import unique_paths
from backend.agents.agent_runtime.values import string_list, text_or_default
from backend.agents.agent_runtime.scoped_update.runtime_parts.policy import SCOPED_UPDATE_EXPANSION_ALLOWED_EXTENSIONS, SCOPED_UPDATE_EXPANSION_DENIED_FILES, SCOPED_UPDATE_EXPANSION_DENIED_PARTS

def scoped_update_scope_expansion_retry_prompt(prompt: str, event: dict[str, Any]) -> str:
  accepted_paths = string_list(event.get("accepted_paths"), [])
  return (
    f"{prompt}\n\n"
    "The runtime safely expanded this subtask's internal file scope after your request. "
    f"The next available file is: {', '.join(accepted_paths)}. "
    "Apply the requested change now. Do not ask the user for permission to modify these files."
  )


def scoped_update_expansion_file_rejection(path: str, content: str, *, request_kind: str = "") -> str:
  try:
    from backend.agents.platform_file_locks import (
      is_locked_platform_update_path,
      is_platform_lock_exempt_for_request,
    )
  except ImportError:
    from agents.platform_file_locks import (
      is_locked_platform_update_path,
      is_platform_lock_exempt_for_request,
    )
  if is_locked_platform_update_path(path) and not is_platform_lock_exempt_for_request(path, request_kind=request_kind):
    return "the file is platform-managed and cannot be edited during website updates"
  lowered_path = path.lower()
  parts = {part for part in lowered_path.split("/") if part}
  basename = lowered_path.rsplit("/", 1)[-1]
  if parts & SCOPED_UPDATE_EXPANSION_DENIED_PARTS:
    return "the path is inside a generated, cached, or vendor directory"
  if basename in SCOPED_UPDATE_EXPANSION_DENIED_FILES:
    return "the file is generated, credential-related, or lock-managed"
  if basename.startswith(".env") and basename != ".env.example":
    return "environment secret files cannot be added to autonomous edit scope"
  if len(content) > 160000:
    return "the file is too large for a safe model patch"
  if "\x00" in content or content.lstrip().lower().startswith("data:"):
    return "binary or encoded asset files cannot be edited by the scoped patch model"
  if basename != ".env.example" and not lowered_path.endswith(SCOPED_UPDATE_EXPANSION_ALLOWED_EXTENSIONS):
    return "the file type is not supported for autonomous scoped editing"
  return ""


def resolve_scoped_update_scope_expansion(
  response: dict[str, Any],
  *,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  retry_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
  requested_raw = unique_paths(string_list(response.get("requested_files"), []))
  if not requested_raw:
    raise ScopedUpdateGuardError(
      "Scoped update requested internal scope expansion without naming an existing project file. "
      "The existing website was preserved."
    )
  if len(requested_raw) > SCOPED_UPDATE_MAX_EXISTING_FILES:
    raise ScopedUpdateGuardError(
      "Scoped update requested too many files for bounded scope expansion. "
      "The existing website was preserved."
    )

  existing_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in existing_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  normalized_requested: list[str] = []
  for raw_path in requested_raw:
    try:
      path = normalize_artifact_path(raw_path.strip("`'\" "))
    except Exception as exc:
      raise ScopedUpdateGuardError(
        f"Scoped update requested an unsafe scope-expansion path {raw_path}: {exc}. "
        "The existing website was preserved."
      ) from exc
    if path not in existing_by_path:
      raise ScopedUpdateGuardError(
        f"Scoped update requested missing project file {path} for scope expansion. "
        "The existing website was preserved."
      )
    rejection = scoped_update_expansion_file_rejection(
      path,
      existing_by_path[path],
      request_kind=text_or_default(update_analysis.get("request_kind"), ""),
    )
    if rejection:
      raise ScopedUpdateGuardError(
        f"Scoped update rejected scope expansion for {path} because {rejection}. "
        "The existing website was preserved."
      )
    if path not in normalized_requested:
      normalized_requested.append(path)

  current_candidates = [
    path
    for path in string_list(update_analysis.get("candidate_files"), [])
    if path in existing_by_path
  ]
  visible_paths = set(string_list(response.get("_candidate_paths"), []))
  accepted_paths = [path for path in normalized_requested if path not in visible_paths]
  if not accepted_paths:
    raise ScopedUpdateGuardError(
      "Scoped update repeatedly requested scope expansion for files already available in the current model step. "
      "The existing website was preserved."
    )
  newly_approved_paths = [path for path in accepted_paths if path not in current_candidates]
  expanded_candidates = unique_paths([*accepted_paths, *current_candidates])
  if len(expanded_candidates) > SCOPED_UPDATE_MAX_EXISTING_FILES:
    raise ScopedUpdateGuardError(
      "Scoped update scope expansion would exceed the four-existing-file safety limit. "
      "The existing website was preserved."
    )

  expanded_analysis = {
    **update_analysis,
    "candidate_files": expanded_candidates,
  }
  event = {
    "retry_count": retry_count,
    "requested_paths": normalized_requested,
    "accepted_paths": accepted_paths,
    "newly_approved_paths": newly_approved_paths,
    "candidate_files": expanded_candidates,
    "reason": (
      text_or_default(response.get("clarification_question"), "")
      or text_or_default(response.get("summary"), "")
      or "The patch model identified another existing project file required for this subtask."
    )[:500],
  }
  return expanded_analysis, event
