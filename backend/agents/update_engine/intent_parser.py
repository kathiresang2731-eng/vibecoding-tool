from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
  from ..chat_history import primary_update_prompt
except ImportError:
  from agents.chat_history import primary_update_prompt


STYLE_REFERENCE_MARKERS = (
  "same as",
  "same like",
  "like the",
  "like ",
  "match ",
  "similar to",
  "use ",
  " colors",
  " colour",
  " styling",
  " style ",
  " look like",
  "same color",
  "same colour",
)

PAGE_TOKENS = (
  "auth",
  "login",
  "signin",
  "sign-in",
  "dashboard",
  "home",
  "marketplace",
  "onboarding",
  "profile",
  "settings",
  "navbar",
  "header",
  "footer",
  "landing",
)


@dataclass
class StyleReferenceIntent:
  request_kind: str
  target_tokens: list[str]
  reference_tokens: list[str]
  target_files: list[str]
  reference_files: list[str]
  style_reference_summary: str


def _prompt_tokens(prompt: str) -> list[str]:
  return [token for token in re.findall(r"[a-z0-9]+", prompt.lower()) if len(token) >= 3]


def _paths_for_tokens(tokens: list[str], paths: list[str], files_map: dict[str, str]) -> list[str]:
  if not tokens:
    return []
  try:
    from ..streaming.task_planner import _mentioned_paths, _page_hint_paths
  except ImportError:
    from agents.streaming.task_planner import _mentioned_paths, _page_hint_paths

  synthetic_prompt = " ".join(tokens)
  matched = _mentioned_paths(synthetic_prompt, paths)
  if not matched:
    matched = _page_hint_paths(synthetic_prompt, paths, files_map)
  if not matched:
    scored: list[tuple[int, str]] = []
    for path in paths:
      base = path.rsplit("/", 1)[-1].lower()
      score = sum(1 for token in tokens if token in base or token in path.lower())
      if score:
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    matched = [path for _, path in scored]
  return list(dict.fromkeys(matched))[:3]


def is_style_reference_prompt(prompt: str) -> bool:
  lowered = primary_update_prompt(prompt).lower()
  if not any(marker in lowered for marker in STYLE_REFERENCE_MARKERS):
    return False
  return any(token in lowered for token in ("color", "colour", "style", "styling", "theme", "palette", "look"))


def _split_target_reference_tokens(prompt: str) -> tuple[list[str], list[str]]:
  """Heuristic split for prompts like 'auth page colors same like dashboard'."""
  lowered = primary_update_prompt(prompt).lower()
  tokens = [token for token in _prompt_tokens(lowered) if token in PAGE_TOKENS or token in {"page", "component"}]
  if len(tokens) < 2:
    return tokens[:1], tokens[1:2]

  reference_markers = ("dashboard", "home", "marketplace", "onboarding", "navbar", "header", "landing")
  target_markers = ("auth", "login", "signin", "onboarding", "profile", "settings", "marketplace")

  ref_tokens = [token for token in tokens if token in reference_markers]
  target_tokens = [token for token in tokens if token in target_markers and token not in ref_tokens]

  if "auth" in lowered or "login" in lowered:
    if "auth" not in target_tokens and "login" not in target_tokens:
      target_tokens = ["auth", *target_tokens]
  if "dashboard" in lowered and "dashboard" not in ref_tokens:
    ref_tokens.append("dashboard")

  if not target_tokens and tokens:
    target_tokens = [tokens[0]]
  if not ref_tokens and len(tokens) >= 2:
    ref_tokens = [tokens[-1]]

  return list(dict.fromkeys(target_tokens))[:2], list(dict.fromkeys(ref_tokens))[:2]


def parse_style_reference_intent(
  prompt: str,
  *,
  paths: list[str],
  files_map: dict[str, str],
) -> StyleReferenceIntent | None:
  scope_prompt = primary_update_prompt(prompt)
  if not is_style_reference_prompt(scope_prompt):
    return None

  target_tokens, reference_tokens = _split_target_reference_tokens(scope_prompt)
  target_files = _paths_for_tokens(target_tokens, paths, files_map)
  reference_files = _paths_for_tokens(reference_tokens, paths, files_map)

  reference_set = set(reference_files)
  target_files = [path for path in target_files if path not in reference_set or path in target_files]
  reference_files = [path for path in reference_files if path not in set(target_files)]

  if not target_files and reference_files:
    target_files, reference_files = reference_files[:1], reference_files[1:2] or reference_files[:1]

  summary = (
    f"Align styling on {', '.join(target_files) or 'target page'} "
    f"to match {', '.join(reference_files) or 'reference page'}."
  )
  return StyleReferenceIntent(
    request_kind="style_reference_update",
    target_tokens=target_tokens,
    reference_tokens=reference_tokens,
    target_files=target_files,
    reference_files=reference_files,
    style_reference_summary=summary,
  )


def extract_style_snippets(files_map: dict[str, str], paths: list[str], *, max_chars: int = 2400) -> list[dict[str, str]]:
  """Extract className / Tailwind / CSS color hints from reference files."""
  snippets: list[dict[str, str]] = []
  patterns = (
    r'className\s*=\s*["`][^"`]{0,400}["`]',
    r'class(?:Name)?\s*=\s*\{[^}]{0,400}\}',
    r'(?:bg|text|border|from|to|via)-[a-z0-9-]+',
    r'--[a-z0-9-]+\s*:\s*[^;]+;',
    r'#[0-9a-fA-F]{3,8}',
  )
  for path in paths:
    content = str(files_map.get(path) or "")
    if not content.strip():
      continue
    hits: list[str] = []
    for pattern in patterns:
      for match in re.finditer(pattern, content):
        snippet = match.group(0).strip()
        if snippet and snippet not in hits:
          hits.append(snippet)
        if len(hits) >= 12:
          break
    if hits:
      body = "\n".join(hits[:12])[:max_chars]
      snippets.append({"path": path, "snippet": body})
  return snippets


def merge_style_reference_into_analysis(
  analysis: dict[str, Any],
  intent: StyleReferenceIntent,
  *,
  files_map: dict[str, str],
) -> dict[str, Any]:
  merged = dict(analysis)
  merged["request_kind"] = "style_reference_update"
  merged["target_files"] = list(intent.target_files)
  merged["reference_files"] = list(intent.reference_files)
  merged["style_reference_summary"] = intent.style_reference_summary

  candidates = list(dict.fromkeys([*intent.target_files, *intent.reference_files, *(merged.get("candidate_files") or [])]))[:6]
  merged["candidate_files"] = candidates
  if len(candidates) >= 2:
    merged["update_mode"] = "feature_patch"
  merged["execution_strategy"] = "scoped_model_patch"
  merged["scope_rationale"] = intent.style_reference_summary
  merged["summary"] = str(merged.get("summary") or intent.style_reference_summary)[:500]
  merged["style_reference_snippets"] = extract_style_snippets(files_map, intent.reference_files)
  return merged
