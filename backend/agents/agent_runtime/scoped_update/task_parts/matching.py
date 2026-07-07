from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ...constants import (
  SCOPED_UPDATE_FUZZY_MIN_CHARS,
  SCOPED_UPDATE_FUZZY_MIN_RATIO,
)
from ...errors import ScopedUpdateGuardError
from ...file_ops import unique_paths
from ...update_analysis import normalize_scoped_update_candidate_new_files
from ...values import string_list, text_or_default


def find_unique_fuzzy_scoped_edit_match(current: str, search: str) -> tuple[int, int] | None:
  normalized_search = normalize_scoped_patch_match_text(search)
  if len(normalized_search) < SCOPED_UPDATE_FUZZY_MIN_CHARS:
    return None

  best: tuple[float, int, int] | None = None
  candidate_lines = current.splitlines(keepends=True)
  search_line_count = max(1, len([line for line in search.splitlines() if line.strip()]))

  for start_line in range(0, len(candidate_lines)):
    for end_line in range(start_line + 1, min(len(candidate_lines), start_line + search_line_count + 4) + 1):
      snippet = "".join(candidate_lines[start_line:end_line])
      normalized_snippet = normalize_scoped_patch_match_text(snippet)
      ratio = SequenceMatcher(None, normalized_search, normalized_snippet).ratio()
      if ratio < SCOPED_UPDATE_FUZZY_MIN_RATIO:
        continue
      start = sum(len(line) for line in candidate_lines[:start_line])
      end = sum(len(line) for line in candidate_lines[:end_line])
      if best is None or ratio > best[0] or (ratio == best[0] and (end - start) < (best[2] - best[1])):
        best = (ratio, start, end)

  if best and best[0] >= SCOPED_UPDATE_FUZZY_MIN_RATIO:
    return best[1], best[2]
  return None


def scoped_span_overlap_ratio(first: tuple[int, int], second: tuple[int, int]) -> float:
  start = max(first[0], second[0])
  end = min(first[1], second[1])
  if end <= start:
    return 0.0
  overlap = end - start
  union = max(first[1], second[1]) - min(first[0], second[0])
  return overlap / union if union else 0.0


def normalize_scoped_patch_match_text(value: str) -> str:
  return "\n".join(line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines() if line.strip())


def align_scoped_replacement_indentation(replacement: str, original_block: str) -> str:
  original_indent = first_non_empty_line_indent(original_block)
  replacement_indent = first_non_empty_line_indent(replacement)
  replacement_text = replacement
  if original_indent and replacement_indent and replacement_indent != original_indent:
    replacement_text = "\n".join(
      f"{original_indent}{line[len(replacement_indent):]}" if line.startswith(replacement_indent) else line
      for line in replacement_text.splitlines()
    )
  elif original_indent and not replacement_indent:
    replacement_text = "\n".join(
      f"{original_indent}{line}" if line.strip() else line
      for line in replacement_text.splitlines()
    )
  if original_block.endswith("\r\n") and not replacement_text.endswith("\r\n"):
    return f"{replacement_text}\r\n"
  if original_block.endswith("\n") and not replacement_text.endswith("\n"):
    return f"{replacement_text}\n"
  return replacement_text


def first_non_empty_line_indent(value: str) -> str:
  for line in value.splitlines():
    if line.strip():
      match = re.match(r"\s*", line)
      return match.group(0) if match else ""
  return ""


def scoped_update_analysis_for_task(
  update_analysis: dict[str, Any],
  task: dict[str, Any],
  working_files: list[dict[str, str]],
  *,
  additional_candidate_files: list[str] | None = None,
) -> dict[str, Any]:
  existing_paths = [
    text_or_default(file_item.get("path"), "")
    for file_item in working_files
    if isinstance(file_item, dict)
  ]
  additional_candidates = [
    path
    for path in string_list(additional_candidate_files, [])
    if path in set(existing_paths)
  ]
  candidate_files = [
    path
    for path in string_list(task.get("candidate_files"), string_list(update_analysis.get("candidate_files"), []))
    if path in set(existing_paths)
  ][:4]
  if not candidate_files:
    candidate_files = [
      path
      for path in string_list(update_analysis.get("candidate_files"), [])
      if path in set(existing_paths)
    ][:4]
  candidate_files = unique_paths([*candidate_files, *additional_candidates])[:4]
  candidate_new_files = normalize_scoped_update_candidate_new_files(
    task.get("candidate_new_files"),
    existing_paths=existing_paths,
    update_mode=text_or_default(update_analysis.get("update_mode"), "feature_patch"),
  )
  return {
    **update_analysis,
    "summary": text_or_default(task.get("summary"), text_or_default(update_analysis.get("summary"), "")),
    "target_symbols": string_list(task.get("target_symbols"), string_list(update_analysis.get("target_symbols"), [])),
    "candidate_files": candidate_files,
    "candidate_new_files": candidate_new_files,
    "scoped_update_tasks": [],
  }


def scoped_update_prompt_for_task(
  *,
  root_prompt: str,
  task: dict[str, Any],
  index: int,
  total: int,
  prior_task_memory: list[str],
  previous_error: str | None,
) -> str:
  memory_text = "\n".join(prior_task_memory[-3:])
  task_prompt = text_or_default(task.get("prompt"), text_or_default(task.get("summary"), root_prompt))
  parts = [
    f"Overall user update request: {root_prompt}",
    f"Scoped subtask {index + 1} of {total}: {task_prompt}",
  ]
  if memory_text:
    parts.append(f"Previously applied subtasks in this run:\n{memory_text}")
  if previous_error:
    parts.append(f"Previous failed attempt context:\n{previous_error[:1200]}")
  parts.append(
    "Apply only this subtask. Preserve changes already made by previous subtasks "
    "and preserve unrelated code."
  )
  return "\n\n".join(parts)


def code_search_matches_for_task(
  code_search_matches: list[dict[str, Any]],
  task_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
  allowed_paths = set(string_list(task_analysis.get("candidate_files"), []))
  filtered = [
    match
    for match in code_search_matches
    if isinstance(match, dict) and text_or_default(match.get("path"), "") in allowed_paths
  ]
  return filtered or code_search_matches


def invalid_scoped_update_json_guard_error(error: Exception, *, phase: str) -> ScopedUpdateGuardError:
  return ScopedUpdateGuardError(
    "Scoped update was blocked before project modification: "
    f"Gemini returned invalid scoped patch JSON {phase}. "
    "The existing website was preserved."
  )


def is_no_patch_scoped_guard_error(error: Exception) -> bool:
  lowered = str(error).lower()
  return (
    "no scoped edits" in lowered
    or "no usable scoped patch" in lowered
    or "no usable edits" in lowered
    or "no effective file changes" in lowered
    or "no safe patch" in lowered
    or "empty patch" in lowered
    or "no scoped edit" in lowered
    or "no scoped patch" in lowered
    or "no changed_files" in lowered
  )


def is_no_effective_scoped_guard_error(error: Exception) -> bool:
  return "no effective file changes" in str(error).lower()
