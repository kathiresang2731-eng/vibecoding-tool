from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

try:
  from ....audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ...artifacts import normalize_artifact_path, normalize_generated_file_code
from ..constants import (
  SCOPED_UPDATE_COMPACT_CONTEXT_FILE_THRESHOLD_CHARS,
  SCOPED_UPDATE_COMPACT_CONTEXT_THRESHOLD_CHARS,
  SCOPED_UPDATE_COMPACT_EXCERPT_MAX_CHARS,
  SCOPED_UPDATE_COMPACT_EXCERPT_MAX_COUNT,
  SCOPED_UPDATE_COMPACT_TERM_MATCH_RADIUS,
  SCOPED_UPDATE_EDIT_PLAN_ANCHOR_MAX_CHARS,
  SCOPED_UPDATE_EDIT_PLAN_MAX_ANCHORS,
  SCOPED_UPDATE_EDIT_PLAN_TERM_MATCH_RADIUS,
  SCOPED_UPDATE_FUZZY_MIN_CHARS,
  SCOPED_UPDATE_FUZZY_MIN_MARGIN,
  SCOPED_UPDATE_FUZZY_MIN_RATIO,
  SCOPED_UPDATE_MAX_EXISTING_FILES,
  SCOPED_UPDATE_MAX_NEW_FILES,
  SCOPED_UPDATE_MAX_FILES_PER_MODEL_STEP,
  SCOPED_UPDATE_MAX_TASKS,
)
from ..errors import ScopedUpdateGuardError, UpdateRequestNeedsClarificationError
from ..file_ops import tool_files_to_artifact_files, unique_paths
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


def find_unique_fuzzy_scoped_edit_match(current: str, search: str) -> tuple[int, int] | None:
  normalized_search = normalize_scoped_patch_match_text(search)
  if len(normalized_search) < 120:
    return None

  current_lines = current.splitlines(keepends=True)
  search_line_count = len([line for line in search.splitlines() if line.strip()])
  if not current_lines or search_line_count < 4:
    return None

  offsets: list[int] = []
  cursor = 0
  for line in current_lines:
    offsets.append(cursor)
    cursor += len(line)

  scored_matches: list[tuple[float, int, int]] = []
  min_window = max(2, search_line_count - 6)
  max_window = min(len(current_lines), search_line_count + 6)
  for window_size in range(min_window, max_window + 1):
    for index in range(0, len(current_lines) - window_size + 1):
      block = "".join(current_lines[index : index + window_size])
      normalized_block = normalize_scoped_patch_match_text(block)
      if not normalized_block:
        continue
      ratio = SequenceMatcher(None, normalized_search, normalized_block).ratio()
      if ratio >= 0.92:
        start = offsets[index]
        scored_matches.append((ratio, start, start + len(block)))

  if not scored_matches:
    return None

  unique_by_span: dict[tuple[int, int], float] = {}
  for ratio, start, end in scored_matches:
    span = (start, end)
    unique_by_span[span] = max(unique_by_span.get(span, 0.0), ratio)

  ranked = sorted(((ratio, span) for span, ratio in unique_by_span.items()), reverse=True)
  best_ratio, best_span = ranked[0]
  competing = [
    (ratio, span)
    for ratio, span in ranked[1:]
    if scoped_span_overlap_ratio(best_span, span) < 0.8
  ]
  second_ratio = competing[0][0] if competing else 0.0
  if best_ratio >= 0.94 and best_ratio - second_ratio >= 0.025:
    return best_span
  return None


def scoped_span_overlap_ratio(first: tuple[int, int], second: tuple[int, int]) -> float:
  overlap = max(0, min(first[1], second[1]) - max(first[0], second[0]))
  shortest = max(1, min(first[1] - first[0], second[1] - second[0]))
  return overlap / shortest


def normalize_scoped_patch_match_text(value: str) -> str:
  return re.sub(r"\s+", " ", value.replace("\r\n", "\n").replace("\r", "\n").strip())


def align_scoped_replacement_indentation(replacement: str, original_block: str) -> str:
  replacement_text = replacement.strip("\n")
  if not replacement_text:
    return replacement

  original_indent = first_non_empty_line_indent(original_block)
  replacement_indent = first_non_empty_line_indent(replacement_text)
  if original_indent and not replacement_indent:
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


def is_no_effective_scoped_guard_error(error: Exception) -> bool:
  return "no effective file changes" in str(error).lower()


def parse_scoped_count_word(value: str) -> int:
  lowered = value.lower().strip()
  if lowered in SCOPED_COUNT_WORDS:
    return SCOPED_COUNT_WORDS[lowered]
  try:
    return max(1, min(12, int(lowered)))
  except ValueError:
    return 1


def expand_counted_content_items(count: int, noun: str) -> list[str]:
  noun_key = noun.lower().strip()
  if noun_key.startswith("tiger"):
    return TIGER_CONTENT_VARIANTS[:count]
  singular = noun_key[:-1] if noun_key.endswith("s") and len(noun_key) > 3 else noun_key
  titled = singular.replace("-", " ").title()
  return [f"{titled} {index + 1}" for index in range(count)]


def scoped_content_items_from_request(
  prompt: str,
  update_analysis: dict[str, Any],
  *,
  task: dict[str, Any] | None = None,
) -> list[str]:
  synthetic_task = task or {
    "prompt": prompt,
    "summary": text_or_default(update_analysis.get("summary"), ""),
  }
  counted_items = counted_scoped_content_items(prompt)
  if counted_items:
    return counted_items
  items = deterministic_feature_items_for_task(synthetic_task, update_analysis)
  if items:
    return items

  cleaned: list[str] = []
  seen: set[str] = set()
  for line in prompt.splitlines():
    match = re.match(r"^\s*(?:\d+[\.\)]|[-*•])\s*(.+)$", line.strip())
    if not match:
      continue
    label = re.sub(r"\s+", " ", match.group(1).replace("\u2019", "'")).strip(" .;:-")
    if not label or len(label.split()) > 8:
      continue
    key = label.lower()
    if key in seen:
      continue
    seen.add(key)
    cleaned.append(label[:80])
  if cleaned:
    return cleaned

  return counted_scoped_content_items(prompt)


def counted_scoped_content_items(value: str) -> list[str]:
  count_match = re.search(
    r"(?:add|include|insert|append|show|display)\s+"
    r"(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:(?:different|unique|new)\s+)?(?P<noun>[a-z][a-z0-9-]*)",
    value,
    re.IGNORECASE,
  )
  if count_match:
    return expand_counted_content_items(
      parse_scoped_count_word(count_match.group("count")),
      count_match.group("noun"),
    )
  article_match = re.search(
    r"(?:add|include|insert|append|show|display)\s+"
    r"(?:a|an|the)\s+(?P<noun>[a-z][a-z0-9-]*)",
    value,
    re.IGNORECASE,
  )
  if article_match:
    return expand_counted_content_items(1, article_match.group("noun"))
  return []


def scoped_update_requests_list_addition(
  prompt: str,
  update_analysis: dict[str, Any],
  items: list[str],
) -> bool:
  if not items:
    return False
  lowered = prompt.lower()
  layout_markers = (
    "redesign",
    "rearrange",
    "restyle",
    "change layout",
    "change color",
    "navbar",
    "footer",
    "hero section",
  )
  if any(marker in lowered for marker in layout_markers):
    return False
  return any(
    marker in lowered
    for marker in ("add", "include", "insert", "append", "more", "another", "extra")
  )


def find_const_array_close_index(content: str, open_bracket_index: int) -> int:
  depth = 0
  for index in range(open_bracket_index, len(content)):
    char = content[index]
    if char == "[":
      depth += 1
    elif char == "]":
      depth -= 1
      if depth == 0:
        return index
  return -1


def score_const_array_name(name: str, prompt: str, path: str) -> int:
  request = prompt.lower()
  path_key = path.lower()
  name_key = name.lower()
  score = 0
  request_tokens = {token for token in re.findall(r"[a-z0-9]+", request) if len(token) >= 3}
  name_tokens = {token for token in re.findall(r"[a-z0-9]+", name_key) if len(token) >= 3}
  score += len(request_tokens & name_tokens) * 40
  if name_key in request:
    score += 100
  singular = name_key.rstrip("s")
  if singular and singular in request:
    score += 60
  if name_key in path_key or singular in path_key:
    score += 80
  return score


def parse_max_id_from_array_body(body: str) -> int:
  ids = [int(value) for value in re.findall(r"\bid\s*:\s*(\d+)", body)]
  return max(ids) if ids else 0


def sample_object_from_array_body(body: str) -> str:
  depth = 0
  start = -1
  for index, char in enumerate(body):
    if char == "{":
      if depth == 0:
        start = index
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0 and start >= 0:
        return body[start : index + 1]
  return ""


def build_array_object_entry(*, sample: str, item_label: str, item_id: int) -> str:
  if not sample:
    return (
      f"    {{ id: {item_id}, name: \"{js_string_literal(item_label)}\", "
      f"description: \"{js_string_literal(component_item_description(item_label))}\" }}"
    )
  entry = sample
  if re.search(r"\bid\s*:", entry):
    entry = re.sub(r"\bid\s*:\s*\d+", f"id: {item_id}", entry, count=1)
  for field in ("name", "title", "label"):
    if re.search(rf"\b{field}\s*:", entry):
      entry = re.sub(
        rf"\b{field}\s*:\s*\"[^\"]*\"",
        f'{field}: "{js_string_literal(item_label)}"',
        entry,
        count=1,
      )
      break
  else:
    trimmed = entry.rstrip()
    if trimmed.endswith("}"):
      inner = trimmed[:-1].rstrip()
      separator = "" if inner.endswith(",") else ", "
      entry = f"{inner}{separator}name: \"{js_string_literal(item_label)}\" }}"
  return "    " + entry.strip()


def append_items_to_const_array_content(
  content: str,
  items: list[str],
  *,
  prompt: str,
  path: str,
) -> str | None:
  best: tuple[int, int, int] | None = None
  for match in CONST_ARRAY_START_PATTERN.finditer(content):
    open_bracket = match.end() - 1
    close_bracket = find_const_array_close_index(content, open_bracket)
    if close_bracket < 0:
      continue
    score = score_const_array_name(match.group("name"), prompt, path)
    if score <= 0:
      continue
    candidate = (score, open_bracket, close_bracket)
    if best is None or candidate[0] > best[0]:
      best = candidate
  if best is None:
    return None

  _, open_bracket, close_bracket = best
  body = content[open_bracket + 1 : close_bracket]
  sample = sample_object_from_array_body(body.strip())
  next_id = parse_max_id_from_array_body(body)
  existing_names = {
    value.lower()
    for value in re.findall(r'\b(?:name|title|label)\s*:\s*"([^"]*)"', body, re.IGNORECASE)
  }
  new_entries: list[str] = []
  for item in items:
    if item.lower() in existing_names:
      continue
    next_id += 1
    new_entries.append(build_array_object_entry(sample=sample, item_label=item, item_id=next_id))
  if not new_entries:
    return None

  trimmed_body = body.strip()
  if not trimmed_body:
    prefix = "\n"
  elif trimmed_body.endswith(","):
    prefix = "\n"
  else:
    prefix = ",\n"
  insertion = prefix + ",\n".join(new_entries) + "\n  "
  return content[:close_bracket] + insertion + content[close_bracket:]


def deterministic_existing_list_content_update_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  task: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
  items = scoped_content_items_from_request(prompt, update_analysis, task=task)
  if not scoped_update_requests_list_addition(prompt, update_analysis, items):
    return []
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []

  best_match: tuple[int, str, str] | None = None
  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths or not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    updated = append_items_to_const_array_content(content, items, prompt=prompt, path=path)
    if not updated or updated == content:
      continue
    score = score_const_array_name("", prompt, path) + len(items) * 5
    for match in CONST_ARRAY_START_PATTERN.finditer(content):
      score = max(score, score_const_array_name(match.group("name"), prompt, path))
    candidate = (score, path, updated)
    if best_match is None or candidate[0] > best_match[0]:
      best_match = candidate
  if best_match is None:
    return []
  _, path, updated = best_match
  return [{"path": path, "content": normalize_generated_file_code(path, updated)}]


def collect_deterministic_scoped_update_fallback_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
) -> tuple[list[dict[str, str]], str]:
  synthetic_task = task or {
    "prompt": prompt,
    "summary": text_or_default(update_analysis.get("summary"), ""),
  }
  working = working_files or existing_files
  created = created_candidate_paths or []
  resolvers: list[tuple[str, Any]] = []
  if created:
    resolvers.append(
      (
        "created_component_content",
        lambda: deterministic_created_component_content_changes(
          task=synthetic_task,
          update_analysis=update_analysis,
          working_files=working,
          created_candidate_paths=created,
        ),
      )
    )
  resolvers.extend(
    [
      (
        "existing_list_content",
        lambda: deterministic_existing_list_content_update_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
          task=synthetic_task,
        ),
      ),
      (
        "new_project_modal_interaction",
        lambda: deterministic_interaction_modal_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "onboarding_chat_flow",
        lambda: deterministic_onboarding_chat_update_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "undefined_reference_fix",
        lambda: deterministic_undefined_reference_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "undefined_name_runtime_fix",
        lambda: deterministic_undefined_name_runtime_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
    ]
  )
  if not created:
    resolvers.append(
      (
        "created_component_content",
        lambda: deterministic_created_component_content_changes(
          task=synthetic_task,
          update_analysis=update_analysis,
          working_files=working,
          created_candidate_paths=created,
        ),
      )
    )
  for fallback_kind, resolver in resolvers:
    changes = resolver()
    valid_changes = non_empty_deterministic_changes(changes)
    if valid_changes:
      return valid_changes, fallback_kind
  return [], ""


def non_empty_deterministic_changes(changes: Any) -> list[dict[str, str]]:
  valid: list[dict[str, str]] = []
  for item in list_value(changes):
    if not isinstance(item, dict):
      continue
    path = text_or_default(item.get("path"), "")
    content = item.get("content")
    if not isinstance(content, str):
      content = item.get("code")
    if not path or not isinstance(content, str) or not content.strip():
      continue
    valid.append({"path": path, "content": content})
  return valid


def deterministic_created_component_content_changes(
  *,
  task: dict[str, Any],
  update_analysis: dict[str, Any],
  working_files: list[dict[str, str]],
  created_candidate_paths: list[str],
) -> list[dict[str, str]]:
  if text_or_default(update_analysis.get("update_mode"), "") != "feature_patch":
    return []
  created_path_set = set(created_candidate_paths)
  if not created_path_set:
    return []
  working_by_path = {
    text_or_default(file_item.get("path"), ""): text_or_default(file_item.get("content"), "")
    for file_item in working_files
    if isinstance(file_item, dict) and text_or_default(file_item.get("path"), "")
  }
  component_path = next(
    (
      path
      for path in created_candidate_paths
      if path in working_by_path and path.endswith((".jsx", ".tsx"))
    ),
    "",
  )
  if not component_path:
    return []
  items = deterministic_feature_items_for_task(task, update_analysis)
  if not items:
    return []
  component_name = component_name_from_path(component_path)
  if not component_name:
    return []
  return [
    {
      "path": component_path,
      "content": deterministic_feature_component_code(
        component_name=component_name,
        items=items,
        feature_plan=object_value(update_analysis.get("feature_plan")),
      ),
    }
  ]


def deterministic_onboarding_chat_update_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  _ = prompt, update_analysis, existing_files
  return []


def deterministic_undefined_name_runtime_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []
  request_text = scoped_update_request_text(prompt, update_analysis)
  lowered = request_text.lower()
  if "name" not in lowered:
    return []
  if "cannot read properties" not in lowered and "undefined (reading" not in lowered:
    return []

  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths or not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    updated = deterministic_undefined_name_runtime_fix_code(path=path, content=content)
    if updated != content and updated.strip():
      return [{"path": path, "content": updated}]
  return []


def deterministic_undefined_name_runtime_fix_code(*, path: str, content: str) -> str:
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return content
  updated = content
  if "config" in updated and ("config.name" in updated or "config={config}" in updated or "useState(null)" in updated):
    updated = ensure_default_config_declaration(updated)
    updated = re.sub(
      r"(const\s+\[\s*config\s*,\s*setConfig\s*\]\s*=\s*useState\()\s*null\s*(\))",
      r"\1DEFAULT_CONFIG\2",
      updated,
      count=1,
    )
    updated = updated.replace("config={config}", "config={config || DEFAULT_CONFIG}")

  fallback_labels = {
    "config": "Worktual AI",
    "setupData": "Worktual AI",
    "workspace": "Workspace",
    "project": "Project",
    "company": "Company",
    "account": "Account",
    "profile": "Profile",
    "customer": "Customer",
    "user": "User",
    "item": "Untitled",
  }
  for identifier, fallback in fallback_labels.items():
    updated = re.sub(rf"\b{re.escape(identifier)}\.name\b", f'({identifier}?.name || "{fallback}")', updated)
  return updated


UNDEFINED_REFERENCE_PATTERNS = (
  re.compile(r"\bReferenceError:\s*([A-Za-z_$][\w$]*)", re.IGNORECASE),
  re.compile(r"\b([A-Za-z_$][\w$]*)\s+is\s+not\s+defined\b", re.IGNORECASE),
)
UNDEFINED_REFERENCE_SKIP_NAMES = {"react", "undefined", "null", "window", "document", "console", "module", "exports"}
JS_IDENTIFIER_NAME_PATTERN = re.compile(r"^[A-Za-z_$][\w$]*$")


def extract_undefined_reference_names(prompt: str, update_analysis: dict[str, Any]) -> list[str]:
  text = scoped_update_request_text(prompt, update_analysis)
  names: list[str] = []
  seen: set[str] = set()
  for pattern in UNDEFINED_REFERENCE_PATTERNS:
    for match in pattern.finditer(text):
      name = text_or_default(match.group(1), "")
      if not name or name.lower() in UNDEFINED_REFERENCE_SKIP_NAMES or name in seen:
        continue
      seen.add(name)
      names.append(name)
  for symbol in string_list(update_analysis.get("target_symbols"), []):
    if (
      not symbol
      or symbol.lower() in UNDEFINED_REFERENCE_SKIP_NAMES
      or symbol in seen
      or not JS_IDENTIFIER_NAME_PATTERN.match(symbol)
    ):
      continue
    seen.add(symbol)
    names.append(symbol)
  return names[:4]


JSX_CONDITIONAL_GUARD_RE = re.compile(r"\{\s*([A-Za-z_$][\w$]*)\s*&&")


def infer_undeclared_jsx_conditional_identifiers(content: str) -> list[str]:
  names: list[str] = []
  seen: set[str] = set()
  for match in JSX_CONDITIONAL_GUARD_RE.finditer(content):
    name = text_or_default(match.group(1), "")
    if not name or name.lower() in UNDEFINED_REFERENCE_SKIP_NAMES or name in seen:
      continue
    if identifier_is_declared_in_content(content, name):
      continue
    seen.add(name)
    names.append(name)
  return names[:4]


def identifier_is_declared_in_content(content: str, identifier: str) -> bool:
  patterns = (
    rf"\b(?:const|let|var|function)\s+{re.escape(identifier)}\b",
    rf"\b(?:const|let|var)\s+\[[^\]]*\b{re.escape(identifier)}\b",
    rf"import\s+.+\b{re.escape(identifier)}\b",
    rf"\bfunction\s+{re.escape(identifier)}\s*\(",
  )
  return any(re.search(pattern, content) for pattern in patterns)


def _remove_braced_expression_block(content: str, *, start_index: int) -> str:
  depth = 0
  for idx in range(start_index, len(content)):
    char = content[idx]
    if char == "{":
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0:
        return content[:start_index] + content[idx + 1 :]
  return content


def remove_undeclared_identifier_usage(content: str, identifier: str) -> str:
  if identifier_is_declared_in_content(content, identifier):
    return content

  updated = content
  search_from = 0
  while search_from < len(updated):
    match = re.search(rf"\{{\s*{re.escape(identifier)}\s*&&", updated[search_from:])
    if not match:
      break
    start = search_from + match.start()
    updated = _remove_braced_expression_block(updated, start_index=start)
    search_from = start

  search_from = 0
  while search_from < len(updated):
    match = re.search(rf"\{{\s*{re.escape(identifier)}\s*\?", updated[search_from:])
    if not match:
      break
    start = search_from + match.start()
    updated = _remove_braced_expression_block(updated, start_index=start)
    search_from = start

  setter = f"set{identifier[0].upper()}{identifier[1:]}" if identifier else ""
  if setter:
    updated = re.sub(rf"^\s*{re.escape(setter)}\([^)]*\);\s*$", "", updated, flags=re.MULTILINE)

  cleaned_lines: list[str] = []
  for line in updated.splitlines():
    if identifier not in line or identifier_is_declared_in_content(line, identifier):
      cleaned_lines.append(line)
      continue
    if re.search(rf"\b{re.escape(identifier)}\b", line):
      continue
    cleaned_lines.append(line)
  updated = "\n".join(cleaned_lines)
  updated = re.sub(r"\n{3,}", "\n\n", updated)
  return updated


def deterministic_undefined_reference_fix_code(*, path: str, content: str, identifiers: list[str]) -> str:
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return content
  updated = content
  for identifier in identifiers:
    updated = remove_undeclared_identifier_usage(updated, identifier)
  return updated


def deterministic_undefined_reference_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  identifiers = extract_undefined_reference_names(prompt, update_analysis)
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []

  if not identifiers and text_or_default(update_analysis.get("update_mode"), "") == "bug_fix":
    for file_item in existing_files:
      path = text_or_default(file_item.get("path"), "")
      content = text_or_default(file_item.get("content"), "")
      if path not in candidate_paths:
        continue
      for name in infer_undeclared_jsx_conditional_identifiers(content):
        if name not in identifiers:
          identifiers.append(name)
      if len(identifiers) >= 4:
        break
  if not identifiers:
    return []

  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths:
      continue
    updated = deterministic_undefined_reference_fix_code(path=path, content=content, identifiers=identifiers)
    normalized = normalize_generated_file_code(path, updated) if updated.strip() else ""
    if normalized and scoped_update_has_effective_change(path, content, normalized):
      return [{"path": path, "content": normalized}]
  return []


def ensure_default_config_declaration(content: str) -> str:
  if "DEFAULT_CONFIG" in content:
    return content
  declaration = 'const DEFAULT_CONFIG = { name: "Worktual AI", companyName: "Worktual AI" };\n\n'
  import_matches = list(re.finditer(r"^import .+?;\s*$", content, flags=re.MULTILINE))
  if not import_matches:
    return declaration + content
  insert_at = import_matches[-1].end()
  return content[:insert_at] + "\n\n" + declaration + content[insert_at:].lstrip("\n")


def scoped_update_request_text(prompt: str, update_analysis: dict[str, Any]) -> str:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  diagnosis = object_value(update_analysis.get("error_diagnosis"))
  parts = [
    prompt,
    text_or_default(update_analysis.get("summary"), ""),
    " ".join(string_list(update_analysis.get("target_symbols"), [])),
    text_or_default(feature_plan.get("name"), ""),
    " ".join(string_list(feature_plan.get("items"), [])),
    text_or_default(feature_plan.get("interaction"), ""),
    " ".join(string_list(diagnosis.get("root_cause_hints"), [])),
    " ".join(string_list(diagnosis.get("categories"), [])),
    " ".join(string_list(diagnosis.get("mentioned_paths"), [])),
  ]
  return " ".join(part for part in parts if part)


def deterministic_onboarding_chat_component_code(path: str) -> str:
  extension = path.rsplit(".", 1)[-1]
  type_suffix = "" if extension == "jsx" else ": Record<string, string>"
  return (
    'import React, { useMemo, useState } from "react";\n\n'
    "const onboardingSteps = [\n"
    "  {\n"
    '    id: "company",\n'
    '    label: "Company basics",\n'
    '    prompt: "Tell me the company name, industry, and the team size.",\n'
    '    helper: "This sets the context for the workspace.",\n'
    '    placeholder: "Worktual, SaaS, 50 people",\n'
    "  },\n"
    "  {\n"
    '    id: "goals",\n'
    '    label: "Primary goals",\n'
    '    prompt: "What should this workspace help your team accomplish first?",\n'
    '    helper: "Focus on the first measurable business outcome.",\n'
    '    placeholder: "Improve lead follow-up speed",\n'
    "  },\n"
    "  {\n"
    '    id: "channels",\n'
    '    label: "Channels",\n'
    '    prompt: "Which customer channels should the AI assistant connect with?",\n'
    '    helper: "Mention web chat, WhatsApp, email, calls, or CRM data.",\n'
    '    placeholder: "Website chat and CRM contacts",\n'
    "  },\n"
    "  {\n"
    '    id: "automation",\n'
    '    label: "Automation style",\n'
    '    prompt: "How proactive should the AI be during onboarding and follow-up?",\n'
    '    helper: "Choose a light assistant or a more automated workflow.",\n'
    '    placeholder: "Suggest next steps but ask before sending",\n'
    "  },\n"
    "  {\n"
    '    id: "review",\n'
    '    label: "Review and launch",\n'
    '    prompt: "Add any approval rules, owner names, or launch notes.",\n'
    '    helper: "The final answer is passed into the project setup.",\n'
    '    placeholder: "Manager approval before customer messages",\n'
    "  },\n"
    "];\n\n"
    "export default function OnboardingWizard({ onComplete = () => {} }) {\n"
    "  const [activeStep, setActiveStep] = useState(0);\n"
    f"  const [answers, setAnswers] = useState({{}}{type_suffix});\n"
    "  const currentStep = onboardingSteps[activeStep];\n"
    "  const progress = Math.round(((activeStep + 1) / onboardingSteps.length) * 100);\n"
    "  const transcript = useMemo(\n"
    "    () => onboardingSteps.slice(0, activeStep + 1).map((step) => ({\n"
    "      ...step,\n"
    '      answer: answers[step.id] || "",\n'
    "    })),\n"
    "    [activeStep, answers],\n"
    "  );\n\n"
    "  const updateAnswer = (value) => {\n"
    "    setAnswers((current) => ({ ...current, [currentStep.id]: value }));\n"
    "  };\n\n"
    "  const goNext = () => {\n"
    "    if (activeStep < onboardingSteps.length - 1) {\n"
    "      setActiveStep((step) => step + 1);\n"
    "      return;\n"
    "    }\n"
    "    onComplete({\n"
    "      answers,\n"
    "      completedSteps: onboardingSteps.length,\n"
    "      completedAt: new Date().toISOString(),\n"
    "    });\n"
    "  };\n\n"
    "  return (\n"
    '    <section className="min-h-[720px] bg-slate-950 px-4 py-8 text-slate-100 sm:px-6 lg:px-8">\n'
    '      <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[0.9fr_1.1fr]">\n'
    '        <aside className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 shadow-2xl shadow-black/20">\n'
    '          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-violet-300">AI onboarding</p>\n'
    '          <h1 className="mt-3 text-3xl font-bold tracking-tight text-white">5-step conversational setup</h1>\n'
    '          <p className="mt-3 text-sm leading-6 text-slate-300">\n'
    "            Guide the user through setup as a focused chat instead of a traditional long form.\n"
    "          </p>\n"
    '          <div className="mt-6 h-2 overflow-hidden rounded-full bg-white/10">\n'
    '            <div className="h-full rounded-full bg-violet-400 transition-all" style={{ width: `${progress}%` }} />\n'
    "          </div>\n"
    '          <p className="mt-3 text-sm text-slate-400">{progress}% complete</p>\n'
    '          <div className="mt-6 space-y-3">\n'
    "            {onboardingSteps.map((step, index) => (\n"
    "              <button\n"
    "                key={step.id}\n"
    '                type="button"\n'
    "                onClick={() => setActiveStep(index)}\n"
    '                className={`w-full rounded-xl border px-4 py-3 text-left transition ${\n'
    "                  index === activeStep\n"
    '                    ? "border-violet-300 bg-violet-400/15 text-white"\n'
    '                    : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/20"\n'
    "                }`}\n"
    "              >\n"
    '                <span className="text-xs font-semibold uppercase text-slate-400">Step {index + 1}</span>\n'
    '                <span className="mt-1 block font-semibold">{step.label}</span>\n'
    "              </button>\n"
    "            ))}\n"
    "          </div>\n"
    "        </aside>\n\n"
    '        <div className="rounded-2xl border border-white/10 bg-slate-900 p-4 shadow-2xl shadow-black/25 sm:p-6">\n'
    '          <div className="flex items-center justify-between border-b border-white/10 pb-4">\n'
    "            <div>\n"
    '              <p className="text-sm font-semibold text-violet-300">Vibe AI</p>\n'
    '              <h2 className="text-xl font-bold text-white">Conversational onboarding chat</h2>\n'
    "            </div>\n"
    '            <span className="rounded-full bg-emerald-400/15 px-3 py-1 text-xs font-semibold text-emerald-200">Live</span>\n'
    "          </div>\n\n"
    '          <div className="mt-6 space-y-5">\n'
    "            {transcript.map((step, index) => (\n"
    '              <div key={step.id} className="space-y-3">\n'
    '                <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-white/10 px-4 py-3">\n'
    '                  <p className="text-sm font-semibold text-violet-200">AI Assistant · Step {index + 1}</p>\n'
    '                  <p className="mt-1 text-sm leading-6 text-white">{step.prompt}</p>\n'
    '                  <p className="mt-2 text-xs text-slate-400">{step.helper}</p>\n'
    "                </div>\n"
    "                {step.answer && (\n"
    '                  <div className="ml-auto max-w-[88%] rounded-2xl rounded-tr-sm bg-violet-500 px-4 py-3 text-white">\n'
    '                    <p className="text-xs font-semibold uppercase text-violet-100">You</p>\n'
    '                    <p className="mt-1 text-sm leading-6">{step.answer}</p>\n'
    "                  </div>\n"
    "                )}\n"
    "              </div>\n"
    "            ))}\n"
    "          </div>\n\n"
    '          <div className="mt-6 rounded-2xl border border-white/10 bg-slate-950 p-4">\n'
    '            <label className="text-sm font-semibold text-slate-200" htmlFor="onboarding-answer">\n'
    "              {currentStep.label}\n"
    "            </label>\n"
    "            <textarea\n"
    '              id="onboarding-answer"\n'
    '              className="mt-3 min-h-28 w-full resize-none rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-violet-300"\n'
    "              value={answers[currentStep.id] || \"\"}\n"
    "              onChange={(event) => updateAnswer(event.target.value)}\n"
    "              placeholder={currentStep.placeholder}\n"
    "            />\n"
    '            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">\n'
    "              <button\n"
    '                type="button"\n'
    "                onClick={() => setActiveStep((step) => Math.max(0, step - 1))}\n"
    "                disabled={activeStep === 0}\n"
    '                className="rounded-xl border border-white/10 px-4 py-2 text-sm font-semibold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40"\n'
    "              >\n"
    "                Back\n"
    "              </button>\n"
    '              <div className="flex gap-3">\n'
    "                <button\n"
    '                  type="button"\n'
    "                  onClick={goNext}\n"
    '                  className="rounded-xl bg-violet-400 px-5 py-2 text-sm font-bold text-slate-950 shadow-lg shadow-violet-500/20 hover:bg-violet-300"\n'
    "                >\n"
    "                  {activeStep === onboardingSteps.length - 1 ? \"Complete setup\" : \"Next step\"}\n"
    "                </button>\n"
    "              </div>\n"
    "            </div>\n"
    "          </div>\n"
    "        </div>\n"
    "      </div>\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )


def deterministic_interaction_modal_fix_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  lowered_prompt = prompt.lower()
  if "new project" not in lowered_prompt:
    return []
  if not any(term in lowered_prompt for term in ("button", "click", "modal", "not working", "no modal")):
    return []

  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    if path not in candidate_paths or not path.endswith((".jsx", ".tsx")):
      continue
    content = text_or_default(file_item.get("content"), "")
    updated = deterministic_new_project_modal_fix_code(content)
    if updated and updated != content:
      return [{"path": path, "content": updated}]
  return []


def deterministic_new_project_modal_fix_code(content: str) -> str:
  button_match = re.search(r"<button\b(?P<attrs>[^>]*)>(?P<body>[\s\S]{0,900}?New Project[\s\S]{0,900}?)</button>", content)
  if not button_match:
    return ""
  button_block = button_match.group(0)
  if "onClick" in button_match.group("attrs"):
    return ""

  updated = ensure_react_use_state_import(content)
  state_name = "isNewProjectModalOpen"
  setter_name = "setIsNewProjectModalOpen"
  if state_name not in updated:
    component_match = re.search(
      r"(?P<decl>(?:export\s+default\s+)?(?:function|const)\s+[A-Z][A-Za-z0-9_]*\s*(?:=\s*\([^)]*\)\s*=>|\([^)]*\))\s*\{)",
      updated,
    )
    if not component_match:
      return ""
    updated = updated[: component_match.end()] + f"\n  const [{state_name}, {setter_name}] = useState(false);" + updated[component_match.end() :]

  new_button_block = button_block.replace("<button", f"<button onClick={{() => {setter_name}(true)}}", 1)
  updated = updated.replace(button_block, new_button_block, 1)

  if "Create New Project" not in updated:
    modal_markup = (
      "\n      {isNewProjectModalOpen && (\n"
      "        <div className=\"fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4\">\n"
      "          <div className=\"w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-950 p-6 shadow-2xl\">\n"
      "            <div className=\"flex items-start justify-between gap-4\">\n"
      "              <div>\n"
      "                <h2 className=\"text-xl font-bold text-white\">Create New Project</h2>\n"
      "                <p className=\"mt-2 text-sm text-zinc-400\">Start a new project from this workspace.</p>\n"
      "              </div>\n"
      "              <button\n"
      "                type=\"button\"\n"
      "                onClick={() => setIsNewProjectModalOpen(false)}\n"
      "                className=\"rounded-lg border border-zinc-700 px-3 py-1 text-sm font-semibold text-zinc-200 hover:bg-zinc-800\"\n"
      "              >\n"
      "                Close\n"
      "              </button>\n"
      "            </div>\n"
      "          </div>\n"
      "        </div>\n"
      "      )}\n"
    )
    updated = insert_jsx_before_last_root_close(updated, modal_markup)
  return updated


def ensure_react_use_state_import(content: str) -> str:
  if re.search(r"import\s+React\s*,\s*\{[^}]*\buseState\b[^}]*\}\s+from\s+['\"]react['\"]", content):
    return content
  if re.search(r"import\s+\{[^}]*\buseState\b[^}]*\}\s+from\s+['\"]react['\"]", content):
    return content
  updated = re.sub(
    r"import\s+React\s+from\s+(['\"]react['\"]);",
    r"import React, { useState } from \1;",
    content,
    count=1,
  )
  if updated != content:
    return updated
  updated = re.sub(
    r"import\s+React\s*,\s*\{([^}]*)\}\s+from\s+(['\"]react['\"]);",
    lambda match: f"import React, {{ {append_named_import(match.group(1), 'useState')} }} from {match.group(2)};",
    content,
    count=1,
  )
  if updated != content:
    return updated
  updated = re.sub(
    r"import\s+\{([^}]*)\}\s+from\s+(['\"]react['\"]);",
    lambda match: f"import {{ {append_named_import(match.group(1), 'useState')} }} from {match.group(2)};",
    content,
    count=1,
  )
  if updated != content:
    return updated
  return f'import {{ useState }} from "react";\n{content}'


def append_named_import(imports: str, name: str) -> str:
  parts = [part.strip() for part in imports.split(",") if part.strip()]
  if name not in parts:
    parts.append(name)
  return ", ".join(parts)


def insert_jsx_before_last_root_close(content: str, insertion: str) -> str:
  candidates = [(index, tag) for tag in ("</main>", "</section>", "</div>") if (index := content.rfind(tag)) >= 0]
  if not candidates:
    return ""
  index, _tag = max(candidates, key=lambda item: item[0])
  return f"{content[:index]}{insertion}{content[index:]}"


def deterministic_feature_items_for_task(task: dict[str, Any], update_analysis: dict[str, Any]) -> list[str]:
  feature_plan = object_value(update_analysis.get("feature_plan"))
  items = string_list(feature_plan.get("items"), [])
  if not items:
    items = scoped_list_items_from_prompt(text_or_default(task.get("prompt"), ""))
  if not items:
    items = scoped_list_items_from_prompt(text_or_default(update_analysis.get("summary"), ""))
  cleaned: list[str] = []
  seen: set[str] = set()
  for item in items:
    label = re.sub(r"\s+", " ", item.replace("\u2019", "'")).strip(" .;:-")
    if not label:
      continue
    key = label.lower()
    if key in seen:
      continue
    seen.add(key)
    cleaned.append(label[:80])
    if len(cleaned) >= 12:
      break
  return cleaned


def component_name_from_path(path: str) -> str:
  basename = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  return sanitize_pascal_component_name(basename)


def deterministic_feature_component_code(
  *,
  component_name: str,
  items: list[str],
  feature_plan: dict[str, Any],
) -> str:
  title = text_or_default(feature_plan.get("name"), component_name)
  interaction = text_or_default(feature_plan.get("interaction"), "")
  tab_entries = ",\n".join(
    (
      "  { "
      f"id: \"{js_string_literal(slug_for_component_item(label))}\", "
      f"label: \"{js_string_literal(label)}\", "
      f"description: \"{js_string_literal(component_item_description(label))}\" "
      "}"
    )
    for label in items
  )
  subtitle = (
    js_string_literal(interaction)
    if interaction
    else "Review the selected record across the requested sections."
  )
  return (
    "import React, { useMemo, useState } from \"react\";\n\n"
    f"const detailTabs = [\n{tab_entries}\n];\n\n"
    f"export default function {component_name}({{ contact = {{}} }}) {{\n"
    "  const [activeTab, setActiveTab] = useState(detailTabs[0]?.id || \"\");\n"
    "  const activeDetail = useMemo(\n"
    "    () => detailTabs.find((item) => item.id === activeTab) || detailTabs[0],\n"
    "    [activeTab]\n"
    "  );\n\n"
    "  return (\n"
    "    <section className=\"contact-detail-page\">\n"
    "      <header className=\"contact-detail-header\">\n"
    f"        <p className=\"contact-detail-eyebrow\">{js_string_literal(title)}</p>\n"
    "        <h2>{contact.name || contact.company || \"Selected contact\"}</h2>\n"
    f"        <p>{subtitle}</p>\n"
    "      </header>\n"
    "      <nav className=\"contact-detail-tabs\" aria-label=\"Contact detail sections\">\n"
    "        {detailTabs.map((tab) => (\n"
    "          <button\n"
    "            key={tab.id}\n"
    "            type=\"button\"\n"
    "            className={tab.id === activeTab ? \"active\" : \"\"}\n"
    "            onClick={() => setActiveTab(tab.id)}\n"
    "          >\n"
    "            {tab.label}\n"
    "          </button>\n"
    "        ))}\n"
    "      </nav>\n"
    "      <article className=\"contact-detail-card\">\n"
    "        <h3>{activeDetail?.label}</h3>\n"
    "        <p>{activeDetail?.description}</p>\n"
    "      </article>\n"
    "    </section>\n"
    "  );\n"
    "}\n"
  )


def slug_for_component_item(value: str) -> str:
  slugged = re.sub(r"[^a-z0-9]+", "-", value.lower().replace("\u2019", "'")).strip("-")
  return slugged or "section"


def component_item_description(value: str) -> str:
  label = value.strip()
  return f"Review {label} details for the selected record."


def js_string_literal(value: str) -> str:
  return (
    str(value)
    .replace("\\", "\\\\")
    .replace("\"", "\\\"")
    .replace("\r", " ")
    .replace("\n", " ")
  )


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


def validate_scoped_update_changes(
  response: Any,
  *,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
) -> list[dict[str, str]]:
  raw = normalize_scoped_update_response(response)
  status = text_or_default(raw.get("status"), "blocked")
  if status == "needs_scope_expansion":
    requested_files = string_list(raw.get("requested_files"), [])
    requested_text = ", ".join(requested_files) if requested_files else "an unspecified project file"
    raise ScopedUpdateGuardError(
      "Scoped update requested unresolved internal scope expansion for "
      f"{requested_text}. The existing website was preserved."
    )
  if status == "needs_clarification":
    clarification = text_or_default(raw.get("clarification_question"), "")
    if not is_actionable_scoped_clarification(clarification):
      raise ScopedUpdateGuardError(
        "Scoped update was blocked before project modification: "
        "Gemini returned no scoped edits or changed files for the approved files."
      )
    raise UpdateRequestNeedsClarificationError(
      "Update request needs clarification before editing files: "
      + text_or_default(clarification, "Please identify the exact update target.")
    )
  if status != "completed":
    reason = (
      text_or_default(raw.get("summary"), "")
      or text_or_default(raw.get("clarification_question"), "")
      or "Gemini returned no scoped edits or changed files for the approved files."
    )
    raise ScopedUpdateGuardError(
      f"Scoped update was blocked before project modification: {reason}"
    )
  allowed_paths = set(string_list(update_analysis.get("candidate_files"), []))
  existing_by_path = {file_item["path"]: file_item["content"] for file_item in existing_files}
  update_mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  approved_new_paths = set(
    normalize_scoped_update_candidate_new_files(
      update_analysis.get("candidate_new_files"),
      existing_paths=list(existing_by_path),
      update_mode=update_mode,
    )
  )
  maximum_change_fraction = 0.45 if update_mode in {"targeted_patch", "bug_fix"} else 0.80
  changed_files: list[dict[str, str]] = []
  changed_existing_paths: set[str] = set()
  changed_new_paths: set[str] = set()
  seen: set[str] = set()
  edited_by_path: dict[str, str] = {}
  for item in list_value(raw.get("edits")):
    if not isinstance(item, dict):
      continue
    try:
      path = normalize_artifact_path(text_or_default(item.get("path"), ""))
    except Exception as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid edit path: {exc}") from exc
    if path not in allowed_paths or path not in existing_by_path:
      raise ScopedUpdateGuardError(f"Scoped update attempted to edit unapproved file {path}.")
    search = item.get("search")
    replacement = item.get("replace")
    if not isinstance(search, str) or not search:
      raise ScopedUpdateGuardError(f"Scoped update returned an empty search snippet for {path}.")
    if not isinstance(replacement, str):
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid replacement snippet for {path}.")
    try:
      expected_replacements = int(item.get("expected_replacements", 1))
    except (TypeError, ValueError) as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid replacement count for {path}.") from exc
    if expected_replacements < 1 or expected_replacements > 20:
      raise ScopedUpdateGuardError(f"Scoped update replacement count for {path} is outside the safe limit.")
    current = edited_by_path.get(path, existing_by_path[path])
    edited_by_path[path] = apply_scoped_update_edit(
      current=current,
      search=search,
      replacement=replacement,
      expected_replacements=expected_replacements,
      path=path,
    )
  if len(list_value(raw.get("edits"))) > 20:
    raise ScopedUpdateGuardError("Scoped update exceeded the twenty-edit safety limit.")
  for path, code in edited_by_path.items():
    seen.add(path)
    normalized_code = normalize_generated_file_code(path, code)
    previous = existing_by_path[path]
    if not scoped_update_has_effective_change(path, previous, code):
      continue
    normalized_previous = normalize_generated_file_code(path, previous)
    change_fraction = 1.0 - SequenceMatcher(None, normalized_previous, normalized_code).ratio()
    allowed_change_fraction = scoped_update_allowed_change_fraction(
      update_analysis,
      path=path,
      previous=previous,
      candidate=normalized_code,
      default=maximum_change_fraction,
    )
    if change_fraction > allowed_change_fraction:
      raise ScopedUpdateGuardError(
        f"Scoped update edits attempted to rewrite too much of {path} "
        f"({change_fraction:.0%} changed; allowed {allowed_change_fraction:.0%}). "
        "The existing website was preserved."
      )
    changed_existing_paths.add(path)
    changed_files.append({"path": path, "content": normalized_code})
  for item in list_value(raw.get("changed_files")):
    if not isinstance(item, dict):
      continue
    try:
      path = normalize_artifact_path(text_or_default(item.get("path"), ""))
    except Exception as exc:
      raise ScopedUpdateGuardError(f"Scoped update returned an invalid path: {exc}") from exc
    if path in seen:
      raise ScopedUpdateGuardError(f"Scoped update returned duplicate changes for {path}.")
    seen.add(path)
    is_existing_path = path in existing_by_path
    is_approved_new_path = path in approved_new_paths
    if is_existing_path and path not in allowed_paths:
      raise ScopedUpdateGuardError(f"Scoped update attempted to modify unapproved file {path}.")
    if not is_existing_path and not is_approved_new_path:
      raise ScopedUpdateGuardError(f"Scoped update attempted to modify unapproved file {path}.")
    code = item.get("code")
    if not isinstance(code, str) or not code.strip():
      raise ScopedUpdateGuardError(f"Scoped update returned empty or invalid code for {path}.")
    normalized_code = normalize_generated_file_code(path, code)
    if is_existing_path:
      previous = existing_by_path[path]
      if not scoped_update_has_effective_change(path, previous, code):
        continue
      normalized_previous = normalize_generated_file_code(path, previous)
      change_fraction = 1.0 - SequenceMatcher(None, normalized_previous, normalized_code).ratio()
      allowed_change_fraction = scoped_update_allowed_change_fraction(
        update_analysis,
        path=path,
        previous=previous,
        candidate=normalized_code,
        default=maximum_change_fraction,
      )
      if change_fraction > allowed_change_fraction:
        raise ScopedUpdateGuardError(
          f"Scoped update attempted to rewrite too much of {path} "
          f"({change_fraction:.0%} changed; allowed {allowed_change_fraction:.0%}). "
          "The existing website was preserved."
        )
      changed_existing_paths.add(path)
    else:
      changed_new_paths.add(path)
    changed_files.append({"path": path, "content": normalized_code})
  if not changed_files:
    raise ScopedUpdateGuardError("Scoped update returned no effective file changes. The existing website was preserved.")
  if changed_new_paths and not changed_existing_paths:
    raise ScopedUpdateGuardError(
      "Scoped update created a new file without modifying an approved existing integration file. "
      "The existing website was preserved."
    )
  if len(changed_existing_paths) > 4:
    raise ScopedUpdateGuardError("Scoped update exceeded the four-existing-file change limit. The existing website was preserved.")
  if len(changed_new_paths) > SCOPED_UPDATE_MAX_NEW_FILES:
    raise ScopedUpdateGuardError("Scoped update exceeded the two-new-file change limit. The existing website was preserved.")
  return changed_files


def scoped_update_allowed_change_fraction(
  update_analysis: dict[str, Any],
  *,
  path: str,
  previous: str,
  candidate: str,
  default: float,
) -> float:
  if is_onboarding_chat_component_rewrite(update_analysis, path=path, previous=previous, candidate=candidate):
    return 1.0
  return default


def is_onboarding_chat_component_rewrite(
  update_analysis: dict[str, Any],
  *,
  path: str,
  previous: str,
  candidate: str,
) -> bool:
  if text_or_default(update_analysis.get("update_mode"), "") != "feature_patch":
    return False
  request_text = scoped_update_request_text("", update_analysis).lower()
  path_key = path.lower()
  if "onboarding" not in request_text or not any(marker in request_text for marker in ("chat", "conversational", "conversation", "ai chat")):
    return False
  if not any(marker in request_text for marker in ("5", "five", "step")):
    return False
  if "onboarding" not in path_key and "wizard" not in path_key:
    return False
  candidate_key = candidate.lower()
  required_markers = ("onboardingsteps", "activestep", "oncomplete")
  return all(marker in candidate_key for marker in required_markers)


def scoped_update_generated_website(
  *,
  title: str,
  prompt: str,
  update_analysis: dict[str, Any],
  candidate_files: list[dict[str, str]],
  changed_paths: list[str],
) -> dict[str, Any]:
  mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  return {
    "title": title,
    "headline": f"{title} scoped update applied",
    "subheadline": f"Applied the requested {mode.replace('_', ' ')} while preserving unrelated project code.",
    "primary_cta": "Review preview",
    "secondary_cta": "Review changed files",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": "#111827",
        "secondary": "#1F4959",
        "accent": "#2563eb",
        "background": "#ffffff",
        "text": "#111827",
      },
      "style_direction": "Preserve the existing website visual design.",
    },
    "sections": [
      {
        "name": "Scoped update",
        "purpose": "Apply only the requested existing-project change.",
        "content": text_or_default(update_analysis.get("summary"), prompt),
        "items": changed_paths,
      }
    ],
    "files": tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_paths),
  }


def scoped_update_workflow_plan(update_analysis: dict[str, Any], changed_paths: list[str]) -> dict[str, Any]:
  mode = text_or_default(update_analysis.get("update_mode"), "targeted_patch")
  scoped_tasks = [
    task for task in list_value(update_analysis.get("scoped_update_tasks")) if isinstance(task, dict)
  ][:SCOPED_UPDATE_MAX_TASKS]
  if len(scoped_tasks) > 1:
    tasks = []
    for index, task in enumerate(scoped_tasks):
      task_id = text_or_default(task.get("id"), f"scoped_update_{index + 1}")
      previous_task_id = text_or_default(scoped_tasks[index - 1].get("id"), f"scoped_update_{index}") if index else ""
      tasks.append(
        {
          "id": task_id,
          "name": text_or_default(task.get("summary"), f"Scoped update step {index + 1}"),
          "required_capability": mode,
          "runtime_action": "RUN_SCOPED_UPDATE_AGENT",
          "dependencies": [previous_task_id] if previous_task_id else [],
          "risk_level": "medium",
          "optional": False,
        }
      )
    task_ids = [task["id"] for task in tasks]
    dependency_graph = {
      task_id: ([task_ids[index - 1]] if index else [])
      for index, task_id in enumerate(task_ids)
    }
  else:
    tasks = [
      {
        "id": "scoped_update",
        "name": "Scoped existing-project update",
        "required_capability": mode,
        "runtime_action": "RUN_SCOPED_UPDATE_AGENT",
        "dependencies": [],
        "risk_level": "medium",
        "optional": False,
      }
    ]
    task_ids = ["scoped_update"]
    dependency_graph = {"scoped_update": []}
  return {
    "domain": "existing_project_update",
    "scope": text_or_default(update_analysis.get("scope"), "small"),
    "tasks": tasks,
    "assignments": [],
    "dependency_graph": dependency_graph,
    "parallel_groups": [[task_id] for task_id in task_ids],
    "completion_proof": ["artifact_valid", "staged_preview_ready", "visual_qa_passed", "files_committed", "memory_prepared"],
    "active_agents": [
      {
        "id": f"{mode}-agent",
        "name": "Scoped Update Agent",
        "role": "Patch only approved existing source files.",
        "capabilities": [mode],
        "lifecycle": "core",
        "assigned_tasks": task_ids,
      }
    ],
    "created_agent_ids": [],
    "reused_agent_ids": [f"{mode}-agent"],
    "planning_source": "gemini_update_analysis_with_python_guardrails",
    "planner_reason": f"Changed only {', '.join(changed_paths)} and skipped the full dynamic workflow.",
  }
