from __future__ import annotations

import re
from typing import Any

try:
  from ....audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ...artifacts import normalize_artifact_path
from ..constants import (
  SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS,
  SCOPED_UPDATE_COMPACT_CONTEXT_THRESHOLD_CHARS,
  SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS,
  SCOPED_UPDATE_COMPACT_EXCERPT_MAX_COUNT,
  SCOPED_UPDATE_COMPACT_TERM_MATCH_RADIUS,
  SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS,
  SCOPED_UPDATE_EDIT_PLAN_MAX_ANCHORS,
  SCOPED_UPDATE_EDIT_PLAN_TERM_MATCH_RADIUS,
  SCOPED_UPDATE_MAX_EXISTING_FILES,
  SCOPED_UPDATE_MAX_NEW_FILES,
)
from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..file_ops import unique_paths
from ..prompts import (
  empty_scoped_update_retry_prompt as render_empty_scoped_update_retry_prompt,
  no_effective_scoped_update_retry_prompt as render_no_effective_scoped_update_retry_prompt,
  render_compact_scoped_update_retry_prompt,
  strict_scoped_update_retry_prompt as render_strict_scoped_update_retry_prompt,
)
from ..update_analysis import (
  code_match_snippet,
  extract_update_search_terms,
  interaction_render_context_snippets,
  normalize_scoped_update_candidate_new_files,
  sanitize_pascal_component_name,
  scoped_list_items_from_prompt,
  unique_snippets,
)
from ..values import list_value, object_value, string_list, text_or_default


def build_compact_scoped_update_retry_prompt(
  user_prompt: str,
  *,
  update_analysis: dict[str, Any],
  candidate_files: list[dict[str, Any]],
  code_search_matches: list[dict[str, Any]],
  retry_reason: str | None = None,
) -> str:
  allowed_paths = [text_or_default(item.get("path"), "") for item in candidate_files if isinstance(item, dict)]
  excerpts = compact_scoped_update_candidate_excerpts(
    user_prompt,
    candidate_files=candidate_files,
    code_search_matches=code_search_matches,
  )
  return render_compact_scoped_update_retry_prompt(
    user_prompt=user_prompt,
    update_analysis=update_analysis,
    allowed_paths=allowed_paths,
    excerpts=excerpts,
    retry_reason=retry_reason,
  )


def build_scoped_edit_plan(
  user_prompt: str,
  *,
  update_analysis: dict[str, Any],
  candidate_files: list[dict[str, Any]],
  code_search_matches: list[dict[str, Any]],
) -> dict[str, Any]:
  allowed_existing_paths = [
    text_or_default(item.get("path"), "")
    for item in candidate_files
    if isinstance(item, dict) and text_or_default(item.get("path"), "")
  ]
  approved_new_paths = string_list(update_analysis.get("candidate_new_files"), [])[:SCOPED_UPDATE_MAX_NEW_FILES]
  anchors_by_path: dict[str, list[dict[str, str]]] = {}
  matches_by_path = {
    text_or_default(match.get("path"), ""): match
    for match in code_search_matches
    if isinstance(match, dict) and text_or_default(match.get("path"), "")
  }
  terms = extract_update_search_terms(
    " ".join(
      [
        user_prompt,
        text_or_default(update_analysis.get("summary"), ""),
        " ".join(string_list(update_analysis.get("target_symbols"), [])),
        " ".join(string_list(object_value(update_analysis.get("feature_plan")).get("items"), [])),
      ]
    )
  )
  for file_item in candidate_files:
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if not path or not content:
      continue
    anchors = scoped_file_edit_anchors(
      path,
      content,
      terms=terms,
      code_search_match=object_value(matches_by_path.get(path)),
    )
    if anchors:
      anchors_by_path[path] = anchors

  operations = [
    {
      "type": "edit_existing_file",
      "path": path,
      "rule": "Use only exact search/replace edits copied from anchors or current file content.",
    }
    for path in allowed_existing_paths
  ]
  if approved_new_paths:
    operations.extend(
      [
        {
          "type": "create_approved_new_file",
          "path": path,
          "rule": "Only changed_files may create this exact path; also edit an existing integration file.",
        }
        for path in approved_new_paths
      ]
    )
  return {
    "planning_source": "python_scoped_code_localizer",
    "scope_contract": {
      "allowed_existing_paths": allowed_existing_paths,
      "approved_new_paths": approved_new_paths,
      "max_existing_files": SCOPED_UPDATE_MAX_EXISTING_FILES,
      "max_new_files": SCOPED_UPDATE_MAX_NEW_FILES,
      "full_regeneration_allowed": bool(update_analysis.get("allow_full_regeneration")),
    },
    "operations": operations,
    "anchors_by_path": anchors_by_path,
    "instructions": [
      "Patch only the anchored code needed for the user request.",
      "Use exact search/replace for existing files; do not return plan-only JSON.",
      "Create a new file only when the path is listed in approved_new_paths.",
      "If creating a new file, integrate it with a minimal import/render edit in an allowed existing file.",
    ],
  }


def scoped_file_edit_anchors(
  path: str,
  content: str,
  *,
  terms: list[str],
  code_search_match: dict[str, Any],
) -> list[dict[str, str]]:
  anchors: list[dict[str, str]] = []
  for label, snippet in (
    ("import_block", leading_import_block(content)),
    ("component_declaration", first_matching_line_snippet(content, component_declaration_pattern())),
    ("export_statement", first_matching_line_snippet(content, re.compile(r"^\s*export\s+", re.MULTILINE))),
  ):
    if snippet:
      anchors.append({"kind": label, "path": path, "snippet": snippet})
  for snippet in list_value(code_search_match.get("snippets")):
    if isinstance(snippet, str) and snippet.strip():
      anchors.append({
        "kind": "code_search_match",
        "path": path,
        "snippet": snippet.strip()[:SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS],
      })
  for term in terms[:8]:
    snippet = code_match_snippet(content, term, radius=SCOPED_UPDATE_EDIT_PLAN_TERM_MATCH_RADIUS)
    if snippet:
      anchors.append({
        "kind": "term_match",
        "path": path,
        "snippet": snippet[:SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS],
      })
  for snippet in interaction_render_context_snippets(content, terms=terms):
    anchors.append({
      "kind": "interaction_render_context",
      "path": path,
      "snippet": snippet[:SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS],
    })
  for snippet in jsx_interaction_anchor_snippets(content):
    anchors.append({
      "kind": "jsx_interaction",
      "path": path,
      "snippet": snippet[:SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS],
    })
  return dedupe_scoped_anchor_snippets(anchors)[:SCOPED_UPDATE_EDIT_PLAN_MAX_ANCHORS]


def leading_import_block(content: str) -> str:
  lines = content.splitlines()
  block: list[str] = []
  for line in lines[:80]:
    stripped = line.strip()
    if stripped.startswith("import "):
      block.append(line)
      continue
    if block and (not stripped or stripped.startswith("//")):
      block.append(line)
      continue
    if block:
      break
  return "\n".join(block[:12]).strip()


def component_declaration_pattern() -> re.Pattern[str]:
  return re.compile(
    r"^\s*(?:export\s+default\s+)?(?:function|const|class)\s+[A-Z][A-Za-z0-9_]*",
    re.MULTILINE,
  )


def first_matching_line_snippet(content: str, pattern: re.Pattern[str]) -> str:
  match = pattern.search(content)
  if not match:
    return ""
  line_start = content.rfind("\n", 0, match.start()) + 1
  line_end = content.find("\n", match.end())
  if line_end < 0:
    line_end = len(content)
  return content[line_start:line_end].strip()


def jsx_interaction_anchor_snippets(content: str) -> list[str]:
  snippets: list[str] = []
  patterns = (
    r"<button\b[^>]*>.*?</button>",
    r"<a\b[^>]*>.*?</a>",
    r"\.map\([^)]*=>\s*\(",
    r"onClick\s*=",
    r"onChange\s*=",
  )
  for pattern in patterns:
    for match in re.finditer(pattern, content, flags=re.IGNORECASE | re.DOTALL):
      start = max(0, match.start() - 220)
      end = min(len(content), match.end() + 220)
      snippet = content[start:end].strip()
      if snippet:
        snippets.append(snippet)
      if len(snippets) >= 6:
        return snippets
  return snippets


def dedupe_scoped_anchor_snippets(anchors: list[dict[str, str]]) -> list[dict[str, str]]:
  deduped: list[dict[str, str]] = []
  seen: set[str] = set()
  for anchor in anchors:
    snippet = text_or_default(anchor.get("snippet"), "").strip()
    key = re.sub(r"\s+", " ", snippet)
    if not snippet or key in seen:
      continue
    seen.add(key)
    deduped.append({**anchor, "snippet": snippet})
  return deduped


def log_scoped_no_patch_response(
  response: dict[str, Any],
  *,
  update_analysis: dict[str, Any],
  phase: str,
) -> None:
  edit_plan = object_value(update_analysis.get("scoped_edit_plan"))
  anchors_by_path = object_value(edit_plan.get("anchors_by_path"))
  log_query_event(
    "scoped_update.no_patch_response",
    payload={
      "phase": phase,
      "status": response.get("status"),
      "summary": text_or_default(response.get("summary"), "")[:500],
      "clarification_question": text_or_default(response.get("clarification_question"), "")[:500],
      "requested_files": string_list(response.get("requested_files"), [])[:SCOPED_UPDATE_MAX_EXISTING_FILES],
      "candidate_files": string_list(update_analysis.get("candidate_files"), []),
      "candidate_new_files": string_list(update_analysis.get("candidate_new_files"), []),
      "edit_plan_source": edit_plan.get("planning_source"),
      "anchor_counts": {
        path: len(list_value(anchors))
        for path, anchors in anchors_by_path.items()
      },
      "operations": [
        {
          "type": item.get("type"),
          "path": item.get("path"),
        }
        for item in list_value(edit_plan.get("operations"))
        if isinstance(item, dict)
      ],
    },
  )


def should_use_compact_scoped_update_prompt(
  candidate_files: list[dict[str, Any]],
  *,
  update_analysis: dict[str, Any] | None = None,
) -> bool:
  candidate_sizes = [
    int(item.get("content_chars") or len(text_or_default(item.get("content"), "")))
    for item in candidate_files
    if isinstance(item, dict)
  ]
  total_chars = sum(candidate_sizes)
  largest_file_chars = max(candidate_sizes, default=0)
  update_mode = text_or_default(object_value(update_analysis).get("update_mode"), "")
  if total_chars > SCOPED_UPDATE_COMPACT_CONTEXT_THRESHOLD_CHARS:
    return True
  if largest_file_chars > SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS:
    return True
  if update_mode in {"feature_patch", "bug_fix"} and total_chars > SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS:
    return True
  return len(candidate_sizes) > 1 and total_chars > SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS


def compact_scoped_update_candidate_excerpts(
  user_prompt: str,
  *,
  candidate_files: list[dict[str, Any]],
  code_search_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  terms = extract_update_search_terms(user_prompt)
  snippets_by_path: dict[str, list[str]] = {}
  for match in code_search_matches:
    if not isinstance(match, dict):
      continue
    path = text_or_default(match.get("path"), "")
    if not path:
      continue
    for snippet in list_value(match.get("snippets")):
      if isinstance(snippet, str) and snippet.strip():
        snippets_by_path.setdefault(path, []).append(snippet)

  excerpts: list[dict[str, Any]] = []
  for file_item in candidate_files:
    if not isinstance(file_item, dict):
      continue
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if not path or not content:
      continue
    raw_snippets = structural_scoped_update_file_snippets(content)
    raw_snippets.extend(snippets_by_path.get(path, []))
    for term in terms[:8]:
      snippet = code_match_snippet(content, term, radius=SCOPED_UPDATE_COMPACT_TERM_MATCH_RADIUS)
      if snippet:
        raw_snippets.append(snippet)
    raw_snippets.extend(interaction_render_context_snippets(content, terms=terms))
    if not raw_snippets:
      raw_snippets.extend(fallback_scoped_update_file_snippets(content))
    excerpts.append(
      {
        "path": path,
        "content_chars": len(content),
        "snippets": unique_snippets(
          raw_snippets,
          max_count=SCOPED_UPDATE_COMPACT_EXCERPT_MAX_COUNT,
          max_chars_each=SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS,
        ),
      }
    )
  return excerpts


def fallback_scoped_update_file_snippets(content: str) -> list[str]:
  snippets = structural_scoped_update_file_snippets(content)
  if not snippets:
    snippets = [content[:SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS]]
  if len(content) > 3200:
    snippets.append(content[-SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS:])
  return snippets


def structural_scoped_update_file_snippets(content: str) -> list[str]:
  snippets: list[str] = []
  import_block = leading_import_block(content)
  if import_block:
    snippets.append(import_block)
  else:
    file_header = content[: min(len(content), SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS // 2)].strip()
    if file_header:
      snippets.append(file_header)
  component_setup = component_setup_scoped_update_snippet(content)
  if component_setup:
    snippets.append(component_setup)
  return snippets


def component_setup_scoped_update_snippet(content: str) -> str:
  match = component_declaration_pattern().search(content)
  if not match:
    return ""
  start = content.rfind("\n", 0, match.start()) + 1
  max_chars = SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS // 2
  selected: list[str] = []
  selected_chars = 0
  for line in content[start:].splitlines()[:14]:
    selected.append(line)
    selected_chars += len(line) + 1
    if selected_chars >= max_chars:
      break
  return "\n".join(selected).strip()


def strict_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return render_strict_scoped_update_retry_prompt(scoped_prompt)


def empty_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return render_empty_scoped_update_retry_prompt(scoped_prompt)


def no_effective_scoped_update_retry_prompt(scoped_prompt: str) -> str:
  return render_no_effective_scoped_update_retry_prompt(scoped_prompt)


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
