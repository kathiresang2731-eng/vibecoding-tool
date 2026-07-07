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


def _interaction_contract_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
  interaction = _object_value(analysis.get("interaction"))
  feature_plan = _object_value(analysis.get("feature_plan"))
  component = _text_or_default(
    interaction.get("component")
    or interaction.get("element")
    or interaction.get("name")
    or feature_plan.get("name"),
    "",
  )[:120]
  trigger = _text_or_default(interaction.get("trigger") or interaction.get("action"), "")[:120]
  expected = _text_or_default(
    interaction.get("expected")
    or interaction.get("behavior")
    or interaction.get("outcome")
    or feature_plan.get("interaction")
    or analysis.get("interaction_summary"),
    "",
  )[:240]
  source_page = _text_or_default(
    interaction.get("source_page")
    or interaction.get("source")
    or interaction.get("source_component")
    or interaction.get("from_page"),
    "",
  )[:120]
  target_page_or_route = _text_or_default(
    interaction.get("target_page_or_route")
    or interaction.get("target_route")
    or interaction.get("target_page")
    or interaction.get("destination")
    or interaction.get("to_page"),
    "",
  )[:160]
  try:
    confidence = float(interaction.get("confidence"))
  except (TypeError, ValueError):
    confidence = 0.0
  if confidence <= 0 and any((component, trigger, expected, source_page, target_page_or_route)):
    confidence = 0.6
  return {
    "component": component,
    "trigger": trigger,
    "expected": expected,
    "source_page": source_page,
    "target_page_or_route": target_page_or_route,
    "confidence": max(0.0, min(1.0, confidence)),
  }


def _interaction_contract_has_signal(contract: dict[str, Any]) -> bool:
  return any(
    _text_or_default(contract.get(key), "")
    for key in ("component", "trigger", "expected", "source_page", "target_page_or_route")
  )


def _route_owner_path(path: str, content: str) -> bool:
  lowered_path = path.lower()
  if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
    return False
  if lowered_path.endswith(("worktual-router-shim.jsx", "worktual-router-shim.tsx")):
    return True
  route_signals = (
    "<routes",
    "<route ",
    "createbrowserrouter",
    "creatememoryrouter",
    "hashrouter",
    "browserrouter",
    "navigate to=",
    "usenavigate",
  )
  lowered_content = content.lower()
  return any(signal in lowered_content for signal in route_signals)


def _text_tokens(value: Any) -> set[str]:
  return {
    token
    for token in re.findall(r"[a-z0-9]+", _text_or_default(value, "").lower())
    if len(token) >= 3
  }


def _path_tokens(path: str) -> set[str]:
  return _text_tokens(path.rsplit("/", 1)[-1].rsplit(".", 1)[0]) | _text_tokens(path)


def _paths_matching_contract_label(
  files_map: dict[str, str],
  label: str,
  *,
  limit: int = 3,
) -> list[str]:
  label_tokens = _text_tokens(label)
  if not label_tokens:
    return []
  scored: list[tuple[int, str]] = []
  for path, content in files_map.items():
    lowered_path = path.lower()
    if not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    if any(part in lowered_path.split("/") for part in {"node_modules", "dist", "build", ".git"}):
      continue
    score = len(label_tokens & _path_tokens(path)) * 120
    content_prefix = content[:12000].lower()
    score += sum(45 for token in label_tokens if token in content_prefix)
    if "/pages/" in lowered_path:
      score += 40
    if "/components/" in lowered_path:
      score += 30
    if score > 0:
      scored.append((score, path))
  scored.sort(key=lambda item: (-item[0], item[1]))
  return [path for _, path in scored[:limit]]


def _interaction_support_paths(
  files_map: dict[str, str],
  *,
  candidate_files: list[str],
  reference_files: list[str],
  contract: dict[str, Any],
) -> list[str]:
  source_label = _text_or_default(contract.get("source_page"), "")
  component_label = _text_or_default(contract.get("component"), "")
  target_label = _text_or_default(contract.get("target_page_or_route"), "")
  expected_label = _text_or_default(contract.get("expected"), "")
  route_owner_paths = [
    path
    for path, content in files_map.items()
    if _route_owner_path(path, content)
  ]
  source_paths = _paths_matching_contract_label(files_map, source_label or component_label, limit=3)
  target_paths = _paths_matching_contract_label(files_map, target_label or expected_label, limit=3)
  support_paths = list(
    dict.fromkeys(
      [
        *source_paths,
        *candidate_files,
        *route_owner_paths[:3],
        *target_paths,
        *reference_files,
      ]
    )
  )
  return [path for path in support_paths if path in files_map][:8]


def resolve_enrichment_profile(*, prompt: str, analysis: dict[str, Any]) -> str:
  request_kind = _text_or_default(analysis.get("request_kind"), "other").lower()
  if request_kind == "style_reference_update":
    return PROFILE_STYLE_REFERENCE
  if request_kind == "interaction_wiring_update":
    return PROFILE_INTERACTION_WIRING
  update_mode = _text_or_default(analysis.get("update_mode"), "")
  feature_plan = _object_value(analysis.get("feature_plan"))
  interaction = _interaction_contract_from_analysis(analysis)
  has_interaction_meta = bool(_text_or_default(feature_plan.get("interaction"), ""))
  if request_kind in {"bug_fix", "feature_patch"} or update_mode in {"bug_fix", "feature_patch"}:
    if has_interaction_meta or _interaction_contract_has_signal(interaction):
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
  matched_ui_elements = [
    item
    for item in list(merged.get("matched_ui_elements") or [])
    if isinstance(item, dict)
  ]
  matched_ui_paths = [
    str(item.get("path") or "")
    for item in matched_ui_elements
    if str(item.get("path") or "") in files_map
  ]
  visual_scope = _text_or_default(merged.get("request_kind"), "other") in {"theme_color_update", "style_reference_update"}
  contract = _interaction_contract_from_analysis(merged)
  profile = resolve_enrichment_profile(prompt=prompt, analysis=merged)
  interaction_scope = profile == PROFILE_INTERACTION_WIRING
  if interaction_scope and not _interaction_contract_has_signal(contract):
    contract["expected"] = primary_update_prompt(prompt)[:240]
    try:
      existing_confidence = float(contract.get("confidence") or 0.0)
    except (TypeError, ValueError):
      existing_confidence = 0.0
    contract["confidence"] = max(existing_confidence, 0.45)
  max_candidates = 8 if visual_scope or interaction_scope else 6
  if target_files:
    candidate_files = list(dict.fromkeys([*target_files, *reference_files, *candidate_files]))[:max_candidates]
  if interaction_scope and matched_ui_paths:
    candidate_files = list(dict.fromkeys([*matched_ui_paths, *candidate_files]))[:max_candidates]
    target_files = list(dict.fromkeys([*matched_ui_paths, *target_files]))[:max_candidates]
  if interaction_scope:
    candidate_files = _interaction_support_paths(
      files_map,
      candidate_files=candidate_files,
      reference_files=reference_files,
      contract=contract,
    )[:max_candidates]
  if profile == PROFILE_INTERACTION_WIRING and _text_or_default(merged.get("request_kind"), "other") == "other":
    if _interaction_contract_has_signal(contract) and candidate_files:
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

  if matched_ui_elements:
    existing_keys = {
      re.sub(r"\s+", " ", str(item.get("snippet") or ""))[:400]
      for item in enrichment_snippets
    }
    for item in matched_ui_elements[:12]:
      path = str(item.get("path") or "")
      if path not in files_map:
        continue
      snippet = str(item.get("snippet") or "").strip()
      text = str(item.get("text") or "").strip()
      evidence = (
        f"Rendered UI match: kind={item.get('element_kind') or '-'} "
        f"text={text!r} component={item.get('component') or '-'} "
        f"route={item.get('route') or '-'} line={item.get('line') or '-'} "
        f"purpose={item.get('purpose') or '-'} event={item.get('event') or '-'} "
        f"handler={item.get('handler') or '-'} target={item.get('target') or '-'}\n"
        f"{snippet[:900]}"
      ).strip()
      key = re.sub(r"\s+", " ", evidence)[:400]
      if evidence and key not in existing_keys:
        enrichment_snippets.insert(0, {"path": path, "snippet": evidence, "kind": "ui_knowledge"})
        existing_keys.add(key)

  merged["enrichment_profile"] = profile
  merged["interaction_summary"] = interaction_summary
  merged["interaction"] = {
    "component": _text_or_default(contract.get("component"), "")[:120],
    "trigger": _text_or_default(contract.get("trigger"), "")[:120],
    "expected": _text_or_default(contract.get("expected"), "")[:240] or interaction_summary[:240],
    "source_page": _text_or_default(contract.get("source_page"), "")[:120],
    "target_page_or_route": _text_or_default(contract.get("target_page_or_route"), "")[:160],
    "confidence": contract.get("confidence", 0.0),
  }
  if interaction_scope and candidate_files:
    merged["candidate_files"] = candidate_files
    merged["target_files"] = list(dict.fromkeys([*target_files, *candidate_files]))[:max_candidates]
    merged["scoped_update_tasks"] = [
      {
        "id": "interaction-repair",
        "summary": interaction_summary or _text_or_default(merged.get("summary"), "Repair the requested UI interaction"),
        "prompt": (
          "Repair the interaction contract using the approved source, routing, and target files. "
          "Patch the real handler/navigation/state wiring; request internal scope expansion if an owning file is missing."
        ),
        "candidate_files": candidate_files,
        "paths": candidate_files,
        "candidate_new_files": [],
        "group_paths": True,
        "target_symbols": [
          value
          for value in [
            _text_or_default(contract.get("component"), ""),
            _text_or_default(contract.get("trigger"), ""),
            _text_or_default(contract.get("target_page_or_route"), ""),
          ]
          if value
        ],
      }
    ]
  merged["scope_enrichment_snippets"] = enrichment_snippets
  return merged
