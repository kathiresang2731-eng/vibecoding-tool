"""Cross-user platform learning — anonymized site update/error patterns only (no chat)."""

from __future__ import annotations

from typing import Any

try:
  from ..runtime_config import platform_failed_run_learning_enabled, platform_pattern_min_source_count
except ImportError:
  from agents.runtime_config import platform_failed_run_learning_enabled, platform_pattern_min_source_count

PLATFORM_MEMORY_TYPES = frozenset({"fix_pattern", "workflow", "tool_pattern"})
NON_LEARNABLE_INTENTS = frozenset({"greeting", "conversation", "requirement_confirmation", "needs_more_detail", "project_info"})
SUCCESSFUL_OUTCOMES = frozenset({"completed", "ready", "partial"})
FAILED_OUTCOMES = frozenset({"failed"})
PASSED_PREVIEW_STATUSES = frozenset({"passed", "ready", "built", "completed", "success"})
INJECTABLE_PROMOTION_STATUSES = frozenset(
  {"soft_platform_lesson", "recommended_platform_pattern", "promoted_platform_pattern"}
)
BLOCKED_PROMOTION_STATUSES = frozenset({"blocked_pattern", "blocked", "failed"})


def confidence_tier_for_source_count(source_count: int) -> str:
  count = int(source_count or 0)
  if count >= 5:
    return "promoted_platform_pattern"
  if count >= 2:
    return "recommended_platform_pattern"
  if count >= 1:
    return "soft_platform_lesson"
  return "blocked_pattern"


def platform_pattern_promotion_status(row: dict[str, Any]) -> str:
  metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
  explicit = str(metadata.get("promotion_status") or metadata.get("confidence_tier") or "").strip()
  if explicit:
    return explicit
  return confidence_tier_for_source_count(int(row.get("source_count") or 0))


def platform_pattern_injection_allowed(row: dict[str, Any], *, min_source_count: int | None = None) -> bool:
  if not isinstance(row, dict):
    return False
  metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
  status = platform_pattern_promotion_status(row)
  if status in BLOCKED_PROMOTION_STATUSES:
    return False
  source_count = int(row.get("source_count") or 0)
  if source_count >= max(1, int(min_source_count or 1)):
    return True
  return source_count >= 1 and status in INJECTABLE_PROMOTION_STATUSES


def build_anonymized_platform_summary(
  *,
  memory_type: str,
  domain: str,
  modules: list[str],
  outcome: str,
  error_category: str | None = None,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
) -> str:
  """Technical pattern summary only — never user prompts or chat transcript text."""
  module_label = ", ".join(modules) if modules else "general"
  lines = [
    f"Pattern type: {memory_type}",
    f"Domain: {domain or 'general'}",
    f"Module: {module_label}",
    f"Outcome: {outcome or 'observed'}",
  ]
  if error_category:
    lines.append(f"Error category: {error_category}")
  if preview_status:
    lines.append(f"Preview/build status: {preview_status}")
  return "\n".join(lines)[:2000]


def build_anonymized_platform_title(
  *,
  memory_type: str,
  domain: str,
  modules: list[str],
  error_category: str | None = None,
) -> str:
  module = modules[0] if modules else "general"
  if error_category:
    return f"{memory_type} · {domain}/{module} · {error_category}"[:240]
  return f"{memory_type} · {domain}/{module}"[:240]


def _preview_passed(preview_status: str | None) -> bool:
  normalized = str(preview_status or "").strip().lower()
  if not normalized:
    return False
  return normalized in PASSED_PREVIEW_STATUSES


def is_platform_learnable_run(
  *,
  memory_type: str,
  intent: str,
  outcome: str,
  error_category: str | None,
  changed_paths: list[str] | None,
  preview_status: str | None,
) -> bool:
  if intent in NON_LEARNABLE_INTENTS:
    return False
  if memory_type not in PLATFORM_MEMORY_TYPES:
    return False
  normalized_outcome = str(outcome or "").strip().lower()
  if (
    platform_failed_run_learning_enabled()
    and memory_type == "fix_pattern"
    and normalized_outcome in FAILED_OUTCOMES
    and error_category
  ):
    return True
  if normalized_outcome not in SUCCESSFUL_OUTCOMES:
    return False
  if not changed_paths and not error_category:
    return False
  if memory_type == "fix_pattern":
    return bool(error_category or _preview_passed(preview_status))
  return bool(changed_paths) and _preview_passed(preview_status)


def maybe_promote_episode_to_platform_pattern(
  store: Any,
  *,
  episode: dict[str, Any],
  domain: str,
  modules: list[str],
  intent: str = "",
  error_category: str | None = None,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
) -> dict[str, Any] | None:
  if not episode or not hasattr(store, "upsert_memory_platform_pattern"):
    return None

  memory_type = str(episode.get("memory_type") or "")
  outcome = str(episode.get("outcome") or "")
  if not is_platform_learnable_run(
    memory_type=memory_type,
    intent=intent,
    outcome=outcome,
    error_category=error_category,
    changed_paths=changed_paths,
    preview_status=preview_status,
  ):
    return None

  module = modules[0] if modules else "general"
  pattern_type = memory_type
  title = build_anonymized_platform_title(
    memory_type=memory_type,
    domain=domain,
    modules=modules,
    error_category=error_category,
  )
  summary = build_anonymized_platform_summary(
    memory_type=memory_type,
    domain=domain,
    modules=modules,
    outcome=outcome,
    error_category=error_category,
    changed_paths=changed_paths,
    preview_status=preview_status,
  )
  if not summary.strip():
    return None

  situation = str(episode.get("situation") or "")[:2000]
  improved_behavior = str(episode.get("improved_behavior") or "")[:2000]
  avoid = str(episode.get("avoid") or "")[:2000]

  pattern = store.upsert_memory_platform_pattern(
    domain=domain or "general",
    module=module,
    pattern_type=pattern_type,
    memory_type=memory_type,
    title=title,
    summary=summary,
    situation=situation,
    improved_behavior=improved_behavior,
    avoid=avoid,
    stack_tags=str(episode.get("stack_tags") or "vite,react,tailwind"),
    metadata={
      "source": "anonymized_site_pattern",
      "anonymized": True,
      "contains_chat": False,
      "contains_paths": False,
      "evidence_count": 1,
      "success_count": 1 if str(outcome).lower() in SUCCESSFUL_OUTCOMES else 0,
      "failure_count": 1 if str(outcome).lower() in FAILED_OUTCOMES else 0,
      "confidence_tier": "soft_platform_lesson",
      "promotion_status": "soft_platform_lesson",
      "current_request_overrides": True,
    },
  )
  if pattern and hasattr(store, "record_platform_pattern_event"):
    store.record_platform_pattern_event(
      pattern_id=str(pattern.get("id") or ""),
      domain=domain or "general",
      module=module,
      pattern_type=pattern_type,
      outcome=outcome or "observed",
    )
  return pattern


def select_platform_patterns_for_prompt(
  store: Any,
  *,
  prompt: str,
  domain: str | None = None,
  modules: list[str] | None = None,
  limit: int = 4,
  prefer_successful: bool = False,
) -> list[dict[str, Any]]:
  if store is None or not hasattr(store, "list_memory_platform_patterns"):
    return []
  try:
    from .pattern_retrieval import rank_platform_patterns
  except ImportError:
    from agents.memory.pattern_retrieval import rank_platform_patterns

  results: list[dict[str, Any]] = []
  seen: set[str] = set()
  module_candidates = list(modules or []) + ["general"]
  for module in module_candidates[:4]:
    for row in store.list_memory_platform_patterns(domain=domain, module=module, limit=limit * 2):
      pattern_id = str(row.get("id") or "")
      if pattern_id and pattern_id not in seen:
        seen.add(pattern_id)
        results.append(row)
  if not results and domain:
    for row in store.list_memory_platform_patterns(domain=domain, limit=limit * 2):
      pattern_id = str(row.get("id") or "")
      if pattern_id and pattern_id not in seen:
        seen.add(pattern_id)
        results.append(row)
  if not results:
    results = store.list_memory_platform_patterns(limit=limit * 2)
  min_source_count = platform_pattern_min_source_count()
  injectable = [
    item
    for item in results
    if str(item.get("pattern_type") or "").strip().lower() != "requirement_correction"
    if platform_pattern_injection_allowed(item, min_source_count=min_source_count)
  ]
  if not injectable:
    return []
  if prefer_successful and injectable:
    successful = [
      item
      for item in injectable
      if str(item.get("outcome") or "").strip().lower() in SUCCESSFUL_OUTCOMES
    ]
    if successful:
      injectable = successful
  ranked = rank_platform_patterns(injectable, prompt=prompt, domain=domain, modules=modules)
  return ranked[:limit]
