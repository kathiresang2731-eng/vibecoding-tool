from __future__ import annotations

import re
from typing import Any

try:
  from ..chat_history import primary_update_prompt
except ImportError:
  from agents.chat_history import primary_update_prompt


BRAND_RENAME_MARKERS = (
  "website name",
  "site name",
  "app name",
  "project name",
  "page title",
  "site title",
  "website title",
)

BRAND_SIGNAL_TOKENS = {"name", "title", "brand", "rename", "rebrand"}

RENAME_TARGET_PATTERNS = (
  re.compile(
    r"change\s+(?:the\s+)?(?:website|site|app|project)?\s*(?:name|title|brand)\s+to\s+['\"]?([^'\".\n]+?)(?:['\"]|\.|$|\n)",
    re.IGNORECASE,
  ),
  re.compile(
    r"(?:website|site|app|project)\s+(?:name|title|brand)\s+(?:to|as)\s+['\"]?([^'\".\n]+?)(?:['\"]|\.|$|\n)",
    re.IGNORECASE,
  ),
  re.compile(
    r"(?:rename|rebrand)\s+(?:the\s+)?(?:website|site|app|project)?\s*(?:to|as)\s+['\"]?([^'\".\n]+?)(?:['\"]|\.|$|\n)",
    re.IGNORECASE,
  ),
)

BRAND_TARGET_PATHS = (
  "index.html",
  "package.json",
  "src/components/Navbar.jsx",
  "src/components/Header.jsx",
  "src/App.jsx",
)


def _prompt_tokens(prompt: str) -> set[str]:
  return set(re.findall(r"[a-z0-9]+", prompt.lower()))


def is_brand_rename_prompt(prompt: str) -> bool:
  primary = primary_update_prompt(prompt)
  lowered = primary.lower()
  if any(marker in lowered for marker in BRAND_RENAME_MARKERS):
    return bool(re.search(r"\b(to|as)\b", lowered))
  tokens = _prompt_tokens(primary)
  if not (tokens & BRAND_SIGNAL_TOKENS):
    return False
  if not re.search(r"\b(to|as)\b", lowered):
    return False
  return bool(re.search(r"\b(website|site|app|project|brand|title|name)\b", lowered))


def extract_rename_target(prompt: str) -> str | None:
  text = primary_update_prompt(prompt)
  if not text:
    return None
  for pattern in RENAME_TARGET_PATTERNS:
    match = pattern.search(text)
    if match:
      target = match.group(1).strip().strip("'\"")
      if target:
        return target
  return None


def brand_title_target_paths(paths: list[str]) -> list[str]:
  path_set = set(paths)
  selected: list[str] = []
  for candidate in BRAND_TARGET_PATHS:
    if candidate in path_set:
      selected.append(candidate)
  for path in paths:
    base = path.rsplit("/", 1)[-1].lower()
    if any(token in base for token in ("navbar", "header", "logo", "sidebar")):
      if path not in selected:
        selected.append(path)
  return selected[:4]


def _normalize_match(value: str) -> str:
  return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _target_present(content: str, target: str) -> bool:
  if not content or not target:
    return False
  normalized_content = _normalize_match(content)
  normalized_target = _normalize_match(target)
  if normalized_target in normalized_content:
    return True
  compact_content = re.sub(r"[^a-z0-9]+", "", normalized_content)
  compact_target = re.sub(r"[^a-z0-9]+", "", normalized_target)
  return bool(compact_target and compact_target in compact_content)


def validate_brand_rename(
  prompt: str,
  *,
  files_before: dict[str, str],
  files_after: dict[str, str],
  changed_paths: list[str],
) -> dict[str, Any] | None:
  if not is_brand_rename_prompt(prompt):
    return None
  expected = extract_rename_target(prompt)
  if not expected:
    return {
      "kind": "brand_rename",
      "applied": False,
      "expected": None,
      "matched_paths": [],
      "reason": "Could not parse the requested website name from the prompt.",
    }

  check_paths = brand_title_target_paths(list(files_after))
  if changed_paths:
    check_paths = list(dict.fromkeys([*changed_paths, *check_paths]))

  matched_paths = [
    path
    for path in check_paths
    if _target_present(files_after.get(path, ""), expected)
    and files_before.get(path, "") != files_after.get(path, "")
  ]
  if not matched_paths:
    matched_paths = [path for path in check_paths if _target_present(files_after.get(path, ""), expected)]

  applied = bool(matched_paths)
  return {
    "kind": "brand_rename",
    "applied": applied,
    "expected": expected,
    "matched_paths": matched_paths,
    "checked_paths": check_paths,
    "reason": (
      f"Found {expected!r} in {', '.join(matched_paths)}."
      if applied
      else f"Requested name {expected!r} was not found in updated brand/title files."
    ),
  }


TITLE_TAG_RE = re.compile(r"(<title>)([^<]*)(</title>)", re.IGNORECASE)
PACKAGE_NAME_RE = re.compile(r'("name"\s*:\s*")([^"]*)(")', re.IGNORECASE)
BRAND_TEXT_RE = re.compile(
  r"(>)([A-Za-z][A-Za-z0-9\s&.'\-]{2,60})(<)",
)


def _guess_current_brand(files_map: dict[str, str]) -> str | None:
  index_html = files_map.get("index.html", "")
  match = TITLE_TAG_RE.search(index_html)
  if match:
    return match.group(2).strip()
  for path in files_map:
    if "navbar" in path.lower() or "header" in path.lower():
      content = files_map[path]
      text_match = BRAND_TEXT_RE.search(content)
      if text_match:
        return text_match.group(2).strip()
  return None


def apply_brand_rename_fallback(
  files_map: dict[str, str],
  *,
  target_name: str,
) -> tuple[list[dict[str, str]], list[str]]:
  """Deterministic brand/title rewrite when LLM workers did not persist changes."""
  if not target_name.strip():
    return [], []

  current_brand = _guess_current_brand(files_map)
  updates: dict[str, str] = {}
  target = target_name.strip()

  brand_paths = [
    path
    for path in files_map
    if any(token in path.lower() for token in ("navbar", "header", "logo", "app.jsx"))
  ]
  for path in brand_paths:
    content = files_map.get(path, "")
    if not content:
      continue
    updated = content
    if current_brand and current_brand in content and current_brand != target:
      updated = content.replace(current_brand, target)
    elif target not in content:
      updated = re.sub(
        r"(className=\"[^\"]*(?:brand|logo|site-name)[^\"]*\"[^>]*>)([^<]{2,80})(</)",
        rf"\1{target}\3",
        content,
        count=1,
        flags=re.IGNORECASE,
      )
    if updated != content:
      updates[path] = updated

  changed_paths = sorted(updates)
  write_payload = [{"path": path, "content": updates[path]} for path in changed_paths]
  return write_payload, changed_paths
