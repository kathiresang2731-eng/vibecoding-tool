from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:
  from ..chat_history import primary_update_prompt
  from .intent_parser import extract_style_snippets
except ImportError:
  try:
    from backend.agents.chat_history import primary_update_prompt
    from backend.agents.update_engine.intent_parser import extract_style_snippets
  except ImportError:
    from agents.chat_history import primary_update_prompt
    from agents.update_engine.intent_parser import extract_style_snippets


PROFILE_STYLE_REFERENCE = "style_reference"
PROFILE_INTERACTION_WIRING = "interaction_wiring"
PROFILE_GENERAL_SCOPED = "general_scoped"

INTERACTION_BREAKAGE_MARKERS = (
  "button",
  "click",
  "onclick",
  "cart",
  "handler",
  "not working",
  "doesn't work",
  "does not work",
  "broken",
  "on press",
  "on tap",
)

HANDLER_PATTERNS = (
  r"handle[A-Z][A-Za-z0-9_]*\s*=",
  r"onClick\s*=",
  r"onChange\s*=",
  r"useState\s*\(",
  r"localStorage",
  r"sessionStorage",
  r"navigate\s*\(",
  r"<Link\b[^>]*to\s*=",
  r"addToCart",
  r"setCart",
)


@dataclass
class ScopeEnrichmentSnippet:
  path: str
  snippet: str
  kind: str


def _object_value(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def _text_or_default(value: Any, default: str = "") -> str:
  if value is None:
    return default
  return str(value).strip() or default


def _has_interaction_breakage_language(prompt: str) -> bool:
  lowered = primary_update_prompt(prompt).lower()
  return any(marker in lowered for marker in INTERACTION_BREAKAGE_MARKERS)


def _interaction_summary_from_analysis(analysis: dict[str, Any]) -> str:
  interaction = _object_value(analysis.get("interaction"))
  if any(_text_or_default(interaction.get(key), "") for key in ("component", "trigger", "expected")):
    try:
      from ..agent_runtime.update_analysis import format_interaction_summary
    except ImportError:
      try:
        from backend.agents.agent_runtime.update_analysis import format_interaction_summary
      except ImportError:
        from agents.agent_runtime.update_analysis import format_interaction_summary
    return format_interaction_summary(
      {
        "component": _text_or_default(interaction.get("component"), ""),
        "trigger": _text_or_default(interaction.get("trigger"), ""),
        "expected": _text_or_default(interaction.get("expected"), ""),
      }
    )
  explicit = _text_or_default(analysis.get("interaction_summary"), "")
  if explicit:
    return explicit[:300]
  feature_plan = _object_value(analysis.get("feature_plan"))
  interaction = _text_or_default(feature_plan.get("interaction"), "")
  if interaction:
    return interaction[:300]
  return _text_or_default(analysis.get("summary"), "")[:300]


def resolve_enrichment_profile(*, prompt: str, analysis: dict[str, Any]) -> str:
  request_kind = _text_or_default(analysis.get("request_kind"), "other").lower()
  if request_kind == "style_reference_update":
    return PROFILE_STYLE_REFERENCE
  if request_kind == "interaction_wiring_update":
    return PROFILE_INTERACTION_WIRING
  update_mode = _text_or_default(analysis.get("update_mode"), "")
  feature_plan = _object_value(analysis.get("feature_plan"))
  has_interaction_meta = bool(_text_or_default(feature_plan.get("interaction"), ""))
  if request_kind in {"bug_fix", "feature_patch"} or update_mode in {"bug_fix", "feature_patch"}:
    if has_interaction_meta or _has_interaction_breakage_language(prompt):
      return PROFILE_INTERACTION_WIRING
  if update_mode in {"targeted_patch", "bug_fix", "feature_patch"} and list(analysis.get("candidate_files") or []):
    return PROFILE_GENERAL_SCOPED
  return PROFILE_GENERAL_SCOPED


def _dedupe_snippets(snippets: list[dict[str, str]], *, max_count: int = 12) -> list[dict[str, str]]:
  deduped: list[dict[str, str]] = []
  seen: set[str] = set()
  for item in snippets:
    path = str(item.get("path") or "")
    snippet = str(item.get("snippet") or "").strip()
    kind = str(item.get("kind") or "context")
    if not path or not snippet:
      continue
    key = re.sub(r"\s+", " ", snippet)[:400]
    if key in seen:
      continue
    seen.add(key)
    deduped.append({"path": path, "snippet": snippet, "kind": kind})
    if len(deduped) >= max_count:
      break
  return deduped


def _cap_snippets_by_budget(snippets: list[dict[str, str]], *, max_total_chars: int) -> list[dict[str, str]]:
  capped: list[dict[str, str]] = []
  used = 0
  per_file_budget = max(1200, max_total_chars // max(1, min(3, len(snippets))))
  for item in snippets:
    if used >= max_total_chars:
      break
    snippet = str(item.get("snippet") or "")
    remaining = max_total_chars - used
    limit = min(per_file_budget, remaining)
    if len(snippet) > limit:
      snippet = snippet[:limit].rstrip() + "\n...[truncated]"
    capped.append({**item, "snippet": snippet})
    used += len(snippet)
  return capped


def _load_interaction_helpers() -> tuple[Any, Any, Any, Any]:
  try:
    from ..agent_runtime.update_analysis import (
      extract_update_search_terms,
      interaction_render_context_snippets,
      unique_snippets,
    )
    from ..agent_runtime.scoped_update import jsx_interaction_anchor_snippets
  except ImportError:
    try:
      from backend.agents.agent_runtime.update_analysis import (
        extract_update_search_terms,
        interaction_render_context_snippets,
        unique_snippets,
      )
      from backend.agents.agent_runtime.scoped_update import jsx_interaction_anchor_snippets
    except ImportError:
      from agents.agent_runtime.update_analysis import (
        extract_update_search_terms,
        interaction_render_context_snippets,
        unique_snippets,
      )
      from agents.agent_runtime.scoped_update import jsx_interaction_anchor_snippets
  return extract_update_search_terms, interaction_render_context_snippets, jsx_interaction_anchor_snippets, unique_snippets


def _extract_handler_snippets(content: str, *, max_chars: int = 2000) -> list[str]:
  snippets: list[str] = []
  for pattern in HANDLER_PATTERNS:
    for match in re.finditer(pattern, content, flags=re.IGNORECASE):
      start = max(0, match.start() - 280)
      end = min(len(content), match.end() + 420)
      snippet = content[start:end].strip()
      if snippet:
        snippets.append(snippet)
      if len(snippets) >= 8:
        break
    if len(snippets) >= 8:
      break
  if not snippets and content.strip():
    lines = content.splitlines()
    snippets.append("\n".join(lines[: min(100, len(lines))]))
  return [item[:max_chars] for item in snippets if item.strip()][:6]


def _extract_general_context_snippet(content: str, *, max_chars: int = 2000) -> str:
  if not content.strip():
    return ""
  lines = content.splitlines()
  excerpt = "\n".join(lines[: min(120, len(lines))])
  export_match = re.search(
    r"^\s*(?:export\s+default\s+)?(?:function|const|class)\s+[A-Z]",
    content,
    flags=re.MULTILINE,
  )
  if export_match:
    start = max(0, export_match.start() - 40)
    end = min(len(content), start + max_chars)
    excerpt = content[start:end].strip()
  if len(excerpt) > max_chars:
    excerpt = excerpt[:max_chars].rstrip() + "\n...[truncated]"
  return excerpt


def _interaction_snippets_for_path(
  path: str,
  content: str,
  *,
  search_terms: list[str],
  max_chars: int,
) -> list[dict[str, str]]:
  extract_update_search_terms, interaction_render_context_snippets, jsx_interaction_anchor_snippets, unique_snippets = _load_interaction_helpers()
  terms = search_terms if search_terms else extract_update_search_terms(primary_update_prompt(""))
  collected: list[str] = []
  collected.extend(interaction_render_context_snippets(content, terms=terms))
  collected.extend(jsx_interaction_anchor_snippets(content))
  collected.extend(_extract_handler_snippets(content, max_chars=max_chars))
  unique = unique_snippets(collected, max_count=6, max_chars_each=max_chars)
  if not unique:
    general = _extract_general_context_snippet(content, max_chars=max_chars)
    if general:
      unique = [general]
  return [{"path": path, "snippet": snippet, "kind": "interaction"} for snippet in unique if snippet.strip()]


def build_scope_enrichment_snippets(
  *,
  files_map: dict[str, str],
  candidate_files: list[str],
  reference_files: list[str],
  prompt: str,
  profile: str,
  search_terms: list[str] | None = None,
  max_total_chars: int = 6000,
) -> list[dict[str, str]]:
  """Build compact pre-read snippets for scoped agent context."""
  extract_update_search_terms, _, _, _ = _load_interaction_helpers()
  terms = search_terms if search_terms is not None else extract_update_search_terms(primary_update_prompt(prompt))
  snippets: list[dict[str, str]] = []

  if profile == PROFILE_STYLE_REFERENCE:
    style_paths = reference_files or candidate_files
    for item in extract_style_snippets(files_map, style_paths, max_chars=2400):
      snippets.append({"path": str(item.get("path") or ""), "snippet": str(item.get("snippet") or ""), "kind": "style"})
    for path in candidate_files[:3]:
      content = str(files_map.get(path) or "")
      if not content.strip():
        continue
      general = _extract_general_context_snippet(content, max_chars=1800)
      if general:
        snippets.append({"path": path, "snippet": general, "kind": "context"})
  elif profile == PROFILE_INTERACTION_WIRING:
    paths = list(dict.fromkeys([*candidate_files, *reference_files]))[:4]
    for path in paths:
      content = str(files_map.get(path) or "")
      if not content.strip():
        continue
      snippets.extend(_interaction_snippets_for_path(path, content, search_terms=terms, max_chars=2000))
  else:
    for path in candidate_files[:3]:
      content = str(files_map.get(path) or "")
      if not content.strip():
        continue
      general = _extract_general_context_snippet(content, max_chars=2000)
      if general:
        snippets.append({"path": path, "snippet": general, "kind": "context"})

  deduped = _dedupe_snippets(snippets)
  return _cap_snippets_by_budget(deduped, max_total_chars=max_total_chars)


def apply_scope_enrichment(
  analysis: dict[str, Any],
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
) -> dict[str, Any]:
  """Attach enrichment profile, snippets, and interaction summary to scope analysis."""
  merged = dict(analysis)
  tool_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  ]
  files_map = {item["path"]: item["content"] for item in tool_files}
  candidate_files = [str(path) for path in list(merged.get("candidate_files") or []) if path]
  target_files = [str(path) for path in list(merged.get("target_files") or []) if path]
  reference_files = [str(path) for path in list(merged.get("reference_files") or []) if path]
  if target_files:
    candidate_files = list(dict.fromkeys([*target_files, *reference_files, *candidate_files]))[:6]

  profile = resolve_enrichment_profile(prompt=prompt, analysis=merged)
  if profile == PROFILE_INTERACTION_WIRING and _text_or_default(merged.get("request_kind"), "other") == "other":
    if _has_interaction_breakage_language(prompt) and candidate_files:
      merged["request_kind"] = "interaction_wiring_update"

  interaction_summary = _interaction_summary_from_analysis(merged)
  if profile == PROFILE_INTERACTION_WIRING and not interaction_summary:
    interaction_summary = primary_update_prompt(prompt)[:300]

  enrichment_snippets = build_scope_enrichment_snippets(
    files_map=files_map,
    candidate_files=candidate_files,
    reference_files=reference_files,
    prompt=prompt,
    profile=profile,
    search_terms=None,
  )

  style_snippets = list(merged.get("style_reference_snippets") or [])
  if style_snippets:
    existing_keys = {
      re.sub(r"\s+", " ", str(item.get("snippet") or ""))[:400]
      for item in enrichment_snippets
    }
    for item in style_snippets:
      snippet = str(item.get("snippet") or "").strip()
      key = re.sub(r"\s+", " ", snippet)[:400]
      if snippet and key not in existing_keys:
        enrichment_snippets.append(
          {"path": str(item.get("path") or ""), "snippet": snippet, "kind": "style"}
        )
        existing_keys.add(key)

  merged["enrichment_profile"] = profile
  merged["interaction_summary"] = interaction_summary
  interaction = _object_value(merged.get("interaction"))
  merged["interaction"] = {
    "component": _text_or_default(interaction.get("component"), "")[:120],
    "trigger": _text_or_default(interaction.get("trigger"), "")[:120],
    "expected": _text_or_default(interaction.get("expected"), "")[:240] or interaction_summary[:240],
  }
  merged["scope_enrichment_snippets"] = enrichment_snippets
  return merged
