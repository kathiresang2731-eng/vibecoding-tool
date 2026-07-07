from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from ...artifacts import normalize_artifact_path, normalize_generated_file_code
from ..constants import (
  SCOPED_UPDATE_FUZZY_MIN_CHARS,
  SCOPED_UPDATE_FUZZY_MIN_MARGIN,
  SCOPED_UPDATE_FUZZY_MIN_RATIO,
  SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP,
  SCOPED_UPDATE_MAX_TASKS,
)
from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..file_ops import tool_files_to_artifact_files, unique_paths
from ..update_analysis import (
  normalize_scoped_update_candidate_new_files,
  sanitize_pascal_component_name,
  scoped_list_items_from_prompt,
)
from ..values import list_value, object_value, string_list, text_or_default
from .prompting import (
  build_compact_scoped_update_retry_prompt,
  build_scoped_edit_plan,
  code_search_matches_for_task,
  compact_scoped_update_candidate_excerpts,
  component_declaration_pattern,
  component_setup_scoped_update_snippet,
  dedupe_scoped_anchor_snippets,
  empty_scoped_update_retry_prompt,
  fallback_scoped_update_file_snippets,
  first_matching_line_snippet,
  leading_import_block,
  log_scoped_no_patch_response,
  no_effective_scoped_update_retry_prompt,
  scoped_file_edit_anchors,
  should_use_compact_scoped_update_prompt,
  strict_scoped_update_retry_prompt,
  structural_scoped_update_file_snippets,
)
from .task_parts import (
  align_scoped_replacement_indentation,
  first_non_empty_line_indent,
  find_unique_fuzzy_scoped_edit_match,
  invalid_scoped_update_json_guard_error,
  is_no_effective_scoped_guard_error,
  is_no_patch_scoped_guard_error,
  normalize_scoped_patch_match_text,
  scoped_span_overlap_ratio,
  scoped_update_analysis_for_task,
  scoped_update_prompt_for_task,
)
from .content_parts import *  # noqa: F401,F403

SEARCH_REPLACE_BLOCK_PATTERN = re.compile(
  r"<<<<<<<[ \t]*SEARCH[ \t]*\r?\n"
  r"(?P<search>.*?)"
  r"\r?\n=======[ \t]*\r?\n"
  r"(?P<replace>.*?)"
  r"(?:\r?\n)?>>>>>>>[ \t]*REPLACE",
  re.DOTALL,
)
SEARCH_REPLACE_TEXT_KEYS = (
  "search_replace",
  "searchReplace",
  "search_replace_block",
  "searchReplaceBlock",
  "search_replace_blocks",
  "searchReplaceBlocks",
  "patch_text",
  "patchText",
  "edits_text",
  "editsText",
  "block",
  "blocks",
  "diff",
  "patch",
  "text",
)
SEARCH_REPLACE_PATH_HEADER_PATTERN = re.compile(
  r"(?im)^\s*(?:file|path|filename|###|##|\*\*)\s*[:#*\s`'\"]*"
  r"(?P<path>(?:src|public|app|pages|components|backend|frontend)/[A-Za-z0-9_./@-]+\.[A-Za-z0-9]+|"
  r"(?:index\.html|package\.json|vite\.config\.[A-Za-z0-9]+|tailwind\.config\.[A-Za-z0-9]+|postcss\.config\.[A-Za-z0-9]+))"
)
SCOPED_PROJECT_PATH_PATTERN = re.compile(
  r"(?<![A-Za-z0-9_.-])"
  r"(?P<path>"
  r"(?:src|public|backend|api|app|server|database|db|migrations|alembic|scripts|tests)"
  r"/[A-Za-z0-9_./@-]+\.[A-Za-z0-9]+"
  r"|(?:index\.html|package\.json|requirements\.txt|pyproject\.toml|"
  r"vite\.config\.[A-Za-z0-9]+|tailwind\.config\.[A-Za-z0-9]+|"
  r"postcss\.config\.[A-Za-z0-9]+|tsconfig(?:\.[A-Za-z0-9_-]+)?\.json)"
  r")"
  r"(?![A-Za-z0-9_.-])",
  re.IGNORECASE,
)
LEGACY_SCOPE_PERMISSION_MARKERS = (
  "current plan does not allow",
  "plan does not allow",
  "not allowed to modify",
  "not permitted to modify",
  "need explicit permission",
  "permission to modify",
  "permission to edit",
  "allow me to modify",
  "allow me to edit",
  "approve modifying",
  "approve editing",
  "would require scope expansion",
  "requires scope expansion",
  "require scope expansion",
  "scope expansion to include",
  "outside the approved scope",
  "unapproved file",
)


def normalize_scoped_update_response(response: Any) -> dict[str, Any]:
  raw_text = response if isinstance(response, str) else ""
  raw = parse_scoped_update_json_text(response) if isinstance(response, str) else object_value(response)
  sources = scoped_update_response_sources(raw)
  if raw_text.strip():
    sources.insert(0, {"edits_text": raw_text})

  edit_keys = (
    "edits",
    "changes",
    "patches",
    "updates",
    "file_edits",
    "file_patches",
    "operations",
    "replacements",
    "candidate_changes",
    "search_replace",
    "search_replace_block",
    "search_replace_blocks",
    "edits_text",
    "patch_text",
  )
  edit_candidates = [
    edit
    for source in sources
    for key in edit_keys
    for edit in normalize_scoped_update_edits(source.get(key))
  ]
  edit_candidates.extend(
    edit
    for source in sources
    for key in edit_keys
    if isinstance(source.get(key), str)
    for edit in parse_search_replace_block_edits(
      source.get(key),
      path=scoped_string_field(source, ("path", "file", "file_path", "filename")),
    )
  )
  edits = dedupe_scoped_update_edits(edit_candidates)
  changed_files = dedupe_scoped_update_files(
    file_item
    for source in sources
    for key in (
      "changed_files",
      "changedFiles",
      "files",
      "file_changes",
      "modified_files",
      "updated_files",
      "candidate_changes",
      "changes",
      "patches",
      "updates",
    )
    for file_item in normalize_scoped_update_files(source.get(key))
  )

  status = first_scoped_text_field(sources, ("status", "state", "result_status")).strip()
  requested_files = first_scoped_string_list_field(
    sources,
    ("requested_files", "requestedFiles", "required_files", "requiredFiles", "scope_files", "scopeFiles"),
  )
  clarification_question = first_scoped_text_field(sources, ("clarification_question", "question", "follow_up"))
  legacy_requested_files = legacy_scope_expansion_paths(clarification_question)
  if legacy_requested_files and not requested_files:
    requested_files = legacy_requested_files
  if requested_files and status in {"", "blocked"} and not edits and not changed_files:
    status = "needs_scope_expansion"
  if status == "needs_clarification" and requested_files and not edits and not changed_files:
    status = "needs_scope_expansion"
  if not status:
    status = "needs_clarification" if clarification_question else "completed" if edits or changed_files else "blocked"
  if status not in {"completed", "needs_scope_expansion", "needs_clarification", "blocked"}:
    status = "completed" if edits or changed_files else "blocked"

  summary = first_scoped_text_field(sources, ("summary", "message", "reason", "description")).strip()
  if len(summary) > 500:
    summary = summary[:497].rstrip() + "..."
  if (
    status == "blocked"
    and not edits
    and not changed_files
    and is_actionable_scoped_clarification(clarification_question)
  ):
    status = "needs_clarification"

  return {
    "status": status,
    "summary": summary,
    "edits": edits,
    "changed_files": changed_files,
    "requested_files": unique_paths(requested_files)[:20],
    "clarification_question": clarification_question,
  }


def scoped_update_response_sources(raw: dict[str, Any]) -> list[dict[str, Any]]:
  sources: list[dict[str, Any]] = []
  seen: set[int] = set()

  def add_source(value: Any) -> None:
    parsed = parse_scoped_update_json_text(value) if isinstance(value, str) else object_value(value)
    if not parsed:
      return
    identity = id(parsed)
    if identity in seen:
      return
    seen.add(identity)
    sources.append(parsed)

  add_source(raw)
  index = 0
  while index < len(sources):
    source = sources[index]
    for key in (
      "result",
      "output",
      "response",
      "artifact",
      "scoped_update",
      "update",
      "patch",
      "data",
      "generated_website",
    ):
      add_source(source.get(key))
    index += 1
  return sources or [raw]


def parse_scoped_update_json_text(value: str) -> dict[str, Any]:
  text = value.strip()
  if not text:
    return {}
  if text.startswith("```"):
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
  try:
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}
  except json.JSONDecodeError:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
      if char != "{":
        continue
      try:
        parsed, _end = decoder.raw_decode(text[index:])
      except json.JSONDecodeError:
        continue
      if isinstance(parsed, dict):
        return parsed
  return {}


def first_scoped_text_field(sources: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
  for source in sources:
    for key in keys:
      value = source.get(key)
      if isinstance(value, str) and value.strip():
        return value.strip()
  return ""


def first_scoped_string_list_field(sources: list[dict[str, Any]], keys: tuple[str, ...]) -> list[str]:
  for source in sources:
    for key in keys:
      values = string_list(source.get(key), [])
      if values:
        return values
      value = source.get(key)
      if isinstance(value, str) and value.strip():
        return [value.strip()]
  return []


def legacy_scope_expansion_paths(value: str) -> list[str]:
  lowered = value.lower()
  if not lowered or not any(marker in lowered for marker in LEGACY_SCOPE_PERMISSION_MARKERS):
    return []
  paths: list[str] = []
  for match in SCOPED_PROJECT_PATH_PATTERN.finditer(value):
    raw_path = match.group("path")
    try:
      path = normalize_artifact_path(raw_path)
    except Exception:
      continue
    if path not in paths:
      paths.append(path)
  return paths[:SCOPED_UPDATE_MAX_EXISTING_FILES]


def scoped_string_field(item: dict[str, Any], keys: tuple[str, ...], *, allow_empty: bool = False) -> str | None:
  for key in keys:
    value = item.get(key)
    if isinstance(value, str) and (allow_empty or value.strip()):
      return value
  return None


def scoped_int_field(item: dict[str, Any], *, fallback: int = 1) -> int:
  try:
    return int(
      item.get("expected_replacements")
      or item.get("expectedReplacementCount")
      or item.get("expected_matches")
      or item.get("count")
      or fallback
    )
  except (TypeError, ValueError):
    return fallback


def parse_search_replace_block_edits(
  value: str,
  *,
  path: str | None = None,
  expected_replacements: int = 1,
) -> list[dict[str, Any]]:
  edits: list[dict[str, Any]] = []
  text = value.replace("\r\n", "\n").replace("\r", "\n")
  for match in SEARCH_REPLACE_BLOCK_PATTERN.finditer(text):
    edit_path = path or infer_search_replace_block_path(text[: match.start()])
    if not edit_path:
      continue
    search = match.group("search")
    replace = match.group("replace")
    if not search:
      continue
    edits.append(
      {
        "path": edit_path,
        "search": search,
        "replace": replace,
        "expected_replacements": expected_replacements,
      }
    )
  return edits


def infer_search_replace_block_path(prefix: str) -> str:
  matches = list(SEARCH_REPLACE_PATH_HEADER_PATTERN.finditer(prefix[-1600:]))
  if not matches:
    return ""
  return matches[-1].group("path").strip("`'\"")


def dedupe_scoped_update_edits(edits: Any) -> list[dict[str, Any]]:
  deduped: list[dict[str, Any]] = []
  seen: set[tuple[str, str, str]] = set()
  for edit in edits:
    key = (edit["path"], edit["search"], edit["replace"])
    if key in seen:
      continue
    seen.add(key)
    deduped.append(edit)
  return deduped


def dedupe_scoped_update_files(files: Any) -> list[dict[str, str]]:
  deduped: list[dict[str, str]] = []
  seen: set[tuple[str, str]] = set()
  for file_item in files:
    key = (file_item["path"], file_item["code"])
    if key in seen:
      continue
    seen.add(key)
    deduped.append(file_item)
  return deduped


def normalize_scoped_update_edits(value: Any) -> list[dict[str, Any]]:
  edits: list[dict[str, Any]] = []
  if isinstance(value, str):
    return parse_search_replace_block_edits(value)
  items = [value] if isinstance(value, dict) else list_value(value)
  for item in items:
    if isinstance(item, str):
      edits.extend(parse_search_replace_block_edits(item))
      continue
    if not isinstance(item, dict):
      continue
    path = scoped_string_field(item, ("path", "file", "file_path", "filename"))
    expected_replacements = scoped_int_field(item, fallback=1)
    for key in SEARCH_REPLACE_TEXT_KEYS:
      block_value = item.get(key)
      if isinstance(block_value, str):
        edits.extend(
          parse_search_replace_block_edits(
            block_value,
            path=path,
            expected_replacements=expected_replacements,
          )
        )
    search = scoped_string_field(item, ("search", "find", "old", "old_code", "old_snippet", "before", "original"))
    replace = scoped_string_field(
      item,
      ("replace", "replacement", "new", "new_code", "new_snippet", "after", "updated"),
      allow_empty=True,
    )
    if not path or not isinstance(search, str) or not isinstance(replace, str):
      continue
    edits.append(
      {
        "path": path,
        "search": search,
        "replace": replace,
        "expected_replacements": expected_replacements,
      }
    )
  return edits


def normalize_scoped_update_files(value: Any) -> list[dict[str, str]]:
  changed_files: list[dict[str, str]] = []
  items = [value] if isinstance(value, dict) else list_value(value)
  for item in items:
    if not isinstance(item, dict):
      continue
    path = scoped_string_field(item, ("path", "file", "file_path", "filename"))
    code = scoped_string_field(
      item,
      ("code", "content", "new_code", "updated_code", "source", "body"),
      allow_empty=True,
    )
    if not path or not isinstance(code, str):
      continue
    changed_files.append({"path": path, "code": code})
  return changed_files


def apply_scoped_update_edit(
  *,
  current: str,
  search: str,
  replacement: str,
  expected_replacements: int,
  path: str,
) -> str:
  actual_replacements = current.count(search)
  if actual_replacements == expected_replacements:
    return current.replace(search, replacement, expected_replacements)

  if actual_replacements == 0 and expected_replacements == 1:
    normalized_match = find_unique_normalized_scoped_edit_match(current, search)
    if normalized_match:
      start, end = normalized_match
      original_block = current[start:end]
      adjusted_replacement = align_scoped_replacement_indentation(replacement, original_block)
      return f"{current[:start]}{adjusted_replacement}{current[end:]}"
    fuzzy_match = find_unique_fuzzy_scoped_edit_match(current, search)
    if fuzzy_match:
      start, end = fuzzy_match
      original_block = current[start:end]
      adjusted_replacement = align_scoped_replacement_indentation(replacement, original_block)
      return f"{current[:start]}{adjusted_replacement}{current[end:]}"

  raise ScopedUpdateGuardError(
    f"Scoped update edit for {path} expected {expected_replacements} exact match(es) "
    f"but found {actual_replacements}. The backend also tried unique normalized and fuzzy matches and "
    "could not apply the edit safely. The existing website was preserved."
  )


def find_unique_normalized_scoped_edit_match(current: str, search: str) -> tuple[int, int] | None:
  normalized_search = normalize_scoped_patch_match_text(search)
  if not normalized_search:
    return None

  candidates: list[tuple[int, int]] = []
  stripped_search = search.strip()
  if stripped_search and stripped_search != search:
    start = current.find(stripped_search)
    if start != -1:
      next_start = current.find(stripped_search, start + len(stripped_search))
      if next_start == -1:
        candidates.append((start, start + len(stripped_search)))

  current_lines = current.splitlines(keepends=True)
  search_line_count = max(1, len([line for line in search.splitlines() if line.strip()]))
  if current_lines:
    offsets: list[int] = []
    cursor = 0
    for line in current_lines:
      offsets.append(cursor)
      cursor += len(line)
    min_window = max(1, search_line_count - 3)
    max_window = min(len(current_lines), search_line_count + 3)
    for window_size in range(min_window, max_window + 1):
      for index in range(0, len(current_lines) - window_size + 1):
        block = "".join(current_lines[index : index + window_size])
        if normalize_scoped_patch_match_text(block) == normalized_search:
          start = offsets[index]
          candidates.append((start, start + len(block)))

  unique_candidates = sorted(set(candidates))
  if len(unique_candidates) == 1:
    return unique_candidates[0]
  return None


CONST_ARRAY_START_PATTERN = re.compile(r"const\s+(?P<name>\w+)\s*=\s*\[", re.MULTILINE)
SCOPED_COUNT_WORDS = {
  "one": 1,
  "two": 2,
  "three": 3,
  "four": 4,
  "five": 5,
  "six": 6,
  "seven": 7,
  "eight": 8,
  "nine": 9,
  "ten": 10,
}
TIGER_CONTENT_VARIANTS = [
  "Bengal Tiger",
  "Siberian Tiger",
  "Sumatran Tiger",
  "Indo-Chinese Tiger",
  "Malayan Tiger",
  "South China Tiger",
]


def should_retry_empty_scoped_update_response(response: dict[str, Any]) -> bool:
  if list_value(response.get("edits")) or list_value(response.get("changed_files")):
    return False
  status = text_or_default(response.get("status"), "blocked")
  clarification = text_or_default(response.get("clarification_question"), "")
  if status == "needs_scope_expansion":
    return False
  if status == "needs_clarification":
    return not is_actionable_scoped_clarification(clarification)
  if status == "blocked" and is_actionable_scoped_clarification(clarification):
    return False
  return True


def is_actionable_scoped_clarification(value: str) -> bool:
  if not value:
    return False
  lowered = value.lower()
  source_context_markers = (
    "provide the jsx code",
    "provide the code segment",
    "provide the snippet",
    "provide a snippet",
    "provide the source",
    "provide the file",
    "share the jsx code",
    "share the code segment",
    "share the snippet",
    "share the source",
    "share the file",
    "paste the jsx code",
    "paste the code segment",
    "paste the snippet",
    "paste the source",
    "paste the file",
    "snippet containing",
    "provided snippets",
    "provided snippets do not include",
    "table rendering code",
    "rendering code",
    "table rows",
    "current contents",
    "file contents",
    "source code",
    "code snippet",
    "code segment",
    "top of the file",
    "top of src/",
    "top of `src/",
    "beginning of the file",
    "file header",
    "current excerpts",
    "focused excerpts",
    "excerpts only show",
    "need the top",
    "from `src/",
    "from src/",
  )
  if any(marker in lowered for marker in source_context_markers):
    return False
  generic_markers = (
    "no safe patch",
    "no scoped edit",
    "no usable edit",
    "could not generate",
    "unable to produce",
    "approved files",
  )
  if any(marker in lowered for marker in generic_markers):
    return False
  return "?" in value or lowered.startswith(("please ", "which ", "what ", "where ", "can you ", "should "))


def strip_generated_react_import_preamble(content: str) -> str:
  lines = content.splitlines()
  if lines and lines[0].strip() in {'import React from "react";', "import React from 'react';"}:
    return "\n".join(lines[1:]).lstrip("\n")
  return content


def scoped_update_has_effective_change(path: str, previous: str, candidate: str) -> bool:
  normalized_previous = normalize_generated_file_code(path, previous)
  normalized_candidate = normalize_generated_file_code(path, candidate)
  if normalized_candidate == normalized_previous:
    return False
  stripped_previous = strip_generated_react_import_preamble(normalized_previous)
  stripped_candidate = strip_generated_react_import_preamble(normalized_candidate)
  return stripped_candidate != stripped_previous

