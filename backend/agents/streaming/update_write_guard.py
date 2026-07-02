from __future__ import annotations

import re
from difflib import SequenceMatcher, unified_diff
from typing import Any

TARGETED_UPDATE_CHANGE_FRACTION = 0.45
BROAD_UPDATE_CHANGE_FRACTION = 0.80
STYLE_REFERENCE_CHANGE_FRACTION = 0.65
MAX_UPDATE_EXISTING_FILES = 4

_CLASSNAME_STYLE_PATTERN = re.compile(
  r"className|class=|bg-|text-|border-|from-|to-|via-|#[0-9a-fA-F]{3,8}|--[a-z0-9-]+\s*:",
  re.IGNORECASE,
)
_HANDLER_STATE_PATTERN = re.compile(
  r"onClick|onChange|handle[A-Z]|useState|localStorage|sessionStorage|navigate\s*\(|<Link\b|addToCart|setCart",
  re.IGNORECASE,
)


def _normalize_code(path: str, content: str) -> str:
  try:
    from ..artifacts import normalize_generated_file_code
  except ImportError:
    from agents.artifacts import normalize_generated_file_code
  return normalize_generated_file_code(path, content)


def is_predominantly_classname_style_diff(path: str, previous: str, candidate: str) -> bool:
  if not previous.strip() or previous == candidate:
    return False
  diff_lines = list(
    unified_diff(
      previous.splitlines(),
      candidate.splitlines(),
      fromfile="before",
      tofile="after",
      lineterm="",
    )
  )
  changed_lines = [line[1:] for line in diff_lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
  if not changed_lines:
    return False
  style_lines = sum(1 for line in changed_lines if _CLASSNAME_STYLE_PATTERN.search(line))
  return style_lines / max(1, len(changed_lines)) >= 0.7


def is_predominantly_handler_state_diff(path: str, previous: str, candidate: str) -> bool:
  if not previous.strip() or previous == candidate:
    return False
  diff_lines = list(
    unified_diff(
      previous.splitlines(),
      candidate.splitlines(),
      fromfile="before",
      tofile="after",
      lineterm="",
    )
  )
  changed_lines = [line[1:] for line in diff_lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
  if not changed_lines:
    return False
  handler_lines = sum(1 for line in changed_lines if _HANDLER_STATE_PATTERN.search(line))
  return handler_lines / max(1, len(changed_lines)) >= 0.55


def allowed_change_fraction(
  *,
  update_mode: str | None = None,
  request_kind: str | None = None,
  prompt: str = "",
  path: str = "",
  previous: str = "",
  candidate: str = "",
) -> float:
  kind = str(request_kind or "").strip().lower()
  if kind == "style_reference_update":
    if path and is_predominantly_classname_style_diff(path, previous, candidate):
      return STYLE_REFERENCE_CHANGE_FRACTION
    return STYLE_REFERENCE_CHANGE_FRACTION
  if kind == "interaction_wiring_update":
    if path and is_predominantly_handler_state_diff(path, previous, candidate):
      return BROAD_UPDATE_CHANGE_FRACTION
    return BROAD_UPDATE_CHANGE_FRACTION
  mode = str(update_mode or "").strip().lower()
  if mode == "feature_patch":
    return BROAD_UPDATE_CHANGE_FRACTION
  if mode == "full_regeneration":
    return BROAD_UPDATE_CHANGE_FRACTION
  if mode in {"targeted_patch", "bug_fix"}:
    if path and is_predominantly_classname_style_diff(path, previous, candidate):
      return STYLE_REFERENCE_CHANGE_FRACTION
    return TARGETED_UPDATE_CHANGE_FRACTION
  lowered = str(prompt or "").lower()
  if any(marker in lowered for marker in ("bug", "fix", "error", "broken", "not working", "repair")):
    return TARGETED_UPDATE_CHANGE_FRACTION
  return TARGETED_UPDATE_CHANGE_FRACTION


def is_new_project_path(path: str, previous_content: str | None) -> bool:
  return not str(previous_content or "").strip()


def compute_change_fraction(path: str, previous: str, candidate: str) -> float:
  normalized_previous = _normalize_code(path, previous)
  normalized_candidate = _normalize_code(path, candidate)
  if normalized_previous == normalized_candidate:
    return 0.0
  return 1.0 - SequenceMatcher(None, normalized_previous, normalized_candidate).ratio()


def guard_streaming_file_write(
  path: str,
  content: str,
  previous_content: str | None,
  *,
  update_mode: str | None = None,
  request_kind: str | None = None,
  prompt: str = "",
  via_write_file: bool = True,
  intent: str = "",
  persist_reason: str = "",
) -> dict[str, Any] | None:
  """Return an error payload when a write would rewrite too much of an existing file."""
  try:
    from ..platform_file_locks import guard_locked_platform_write
  except ImportError:
    from agents.platform_file_locks import guard_locked_platform_write

  locked = guard_locked_platform_write(
    path,
    intent=intent,
    persist_reason=persist_reason,
    previous_content=previous_content,
  )
  if locked:
    return locked
  if not via_write_file:
    return None
  if is_new_project_path(path, previous_content):
    return None
  previous = str(previous_content or "")
  fraction = compute_change_fraction(path, previous, content)
  limit = allowed_change_fraction(
    update_mode=update_mode,
    request_kind=request_kind,
    prompt=prompt,
    path=path,
    previous=previous,
    candidate=content,
  )
  if fraction <= limit:
    return None
  return {
    "error": (
      f"Blocked full rewrite of existing file {path} ({fraction:.0%} changed; limit {limit:.0%}). "
      "Use str_replace with a longer exact old_string copied from read_file. "
      "Preserve unrelated layout, copy, and styling."
    ),
    "path": path,
    "recoverable": True,
    "blocked_rewrite": True,
    "change_fraction": round(fraction, 4),
    "allowed_fraction": limit,
  }


def filter_streaming_write_payload(
  files_before_map: dict[str, str],
  write_payload: list[dict[str, str]],
  *,
  update_mode: str | None = None,
  request_kind: str | None = None,
  prompt: str = "",
  intent: str = "website_update",
  persist_reason: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
  """Drop destructive full-file rewrites before commit; keep surgical changes."""
  try:
    from ..platform_file_locks import filter_locked_platform_writes
  except ImportError:
    from agents.platform_file_locks import filter_locked_platform_writes

  write_payload, locked_rejected = filter_locked_platform_writes(
    write_payload,
    files_before_map=files_before_map,
    intent=intent,
    persist_reason=persist_reason,
  )
  accepted: list[dict[str, str]] = []
  rejected: list[dict[str, Any]] = list(locked_rejected)
  changed_existing = 0
  for item in write_payload:
    path = str(item.get("path") or "")
    content = str(item.get("content") or "")
    if not path:
      continue
    previous = files_before_map.get(path)
    if is_new_project_path(path, previous):
      accepted.append({"path": path, "content": content})
      continue
    previous_text = str(previous or "")
    fraction = compute_change_fraction(path, previous_text, content)
    limit = allowed_change_fraction(
      update_mode=update_mode,
      request_kind=request_kind,
      prompt=prompt,
      path=path,
      previous=previous_text,
      candidate=content,
    )
    if fraction > limit:
      rejected.append(
        {
          "path": path,
          "change_fraction": round(fraction, 4),
          "allowed_fraction": limit,
          "reason": "rewrite_exceeds_safe_fraction",
          "gate": "rewrite_guard",
        }
      )
      continue
    changed_existing += 1
    if changed_existing > MAX_UPDATE_EXISTING_FILES:
      rejected.append({"path": path, "reason": "too_many_existing_files_changed", "gate": "rewrite_guard"})
      continue
    accepted.append({"path": path, "content": content})
  return accepted, rejected
