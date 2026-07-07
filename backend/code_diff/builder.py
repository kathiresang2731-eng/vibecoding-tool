from __future__ import annotations

import difflib
from typing import Any

from .constants import MAX_DIFF_CHARS_PER_FILE, MAX_DIFF_FILES, MAX_DIFF_LINES_PER_FILE
from .hashing import hash_text
from .normalization import normalize_file_map

DIFF_NOISE_FILENAMES = frozenset(
  {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
  }
)


def is_hidden_project_file_path(path: str) -> bool:
  return any(segment.startswith(".") for segment in str(path or "").replace("\\", "/").split("/") if segment)


def is_diff_noise_path(path: str) -> bool:
  cleaned = str(path or "").replace("\\", "/").strip()
  if not cleaned:
    return True
  basename = cleaned.rsplit("/", 1)[-1]
  if basename in DIFF_NOISE_FILENAMES:
    return True
  if basename.lower().endswith(".pdf"):
    return True
  return False


def build_project_diff(
  before_files: list[dict[str, Any]] | None,
  after_files: list[dict[str, Any]] | None,
  *,
  max_files: int = MAX_DIFF_FILES,
  compare_mode: str = "all",
) -> dict[str, Any]:
  before = normalize_file_map(before_files)
  after = normalize_file_map(after_files)
  file_diffs: list[dict[str, Any]] = []
  total_added = 0
  total_removed = 0

  if compare_mode == "changed_only":
    candidate_paths = sorted(path for path in after if not is_diff_noise_path(path))
  else:
    candidate_paths = sorted(
      path
      for path in set(before) | set(after)
      if not is_hidden_project_file_path(path) and not is_diff_noise_path(path)
    )

  for path in candidate_paths:
    old_code = before.get(path)
    new_code = after.get(path)
    if old_code == new_code:
      continue

    status = "modified"
    if old_code is None:
      status = "added"
    elif new_code is None:
      status = "removed"

    diff_lines = list(
      difflib.unified_diff(
        (old_code or "").splitlines(),
        (new_code or "").splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
      )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    total_added += added
    total_removed += removed

    truncated = False
    if len(diff_lines) > MAX_DIFF_LINES_PER_FILE:
      diff_lines = diff_lines[:MAX_DIFF_LINES_PER_FILE]
      truncated = True
    diff_text = "\n".join(diff_lines)
    if len(diff_text) > MAX_DIFF_CHARS_PER_FILE:
      diff_text = diff_text[:MAX_DIFF_CHARS_PER_FILE]
      truncated = True

    file_diffs.append(
      {
        "path": path,
        "status": status,
        "added": added,
        "removed": removed,
        "old_hash": hash_text(old_code or ""),
        "new_hash": hash_text(new_code or ""),
        "old_size": len(old_code or ""),
        "new_size": len(new_code or ""),
        "diff": diff_text,
        "truncated": truncated,
      }
    )

  visible_diffs = file_diffs[: max(1, max_files)]
  return {
    "file_count": len(file_diffs),
    "visible_file_count": len(visible_diffs),
    "truncated_files": max(0, len(file_diffs) - len(visible_diffs)),
    "added": total_added,
    "removed": total_removed,
    "diffs": visible_diffs,
  }
