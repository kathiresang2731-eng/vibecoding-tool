from __future__ import annotations

from typing import Any

try:
  from ..runtime_config import platform_failed_run_learning_enabled, platform_pattern_min_source_count
  from .platform_learning import platform_pattern_injection_allowed, platform_pattern_promotion_status
except ImportError:
  from agents.runtime_config import platform_failed_run_learning_enabled, platform_pattern_min_source_count
  from agents.memory.platform_learning import platform_pattern_injection_allowed, platform_pattern_promotion_status


def serialize_platform_pattern(row: dict[str, Any], *, min_source_count: int) -> dict[str, Any]:
  source_count = int(row.get("source_count") or 0)
  metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
  promotion_status = platform_pattern_promotion_status(row)
  return {
    "id": row.get("id"),
    "pattern_key": row.get("pattern_key"),
    "domain": row.get("domain"),
    "module": row.get("module"),
    "pattern_type": row.get("pattern_type"),
    "memory_type": row.get("memory_type"),
    "title": row.get("title") or "",
    "summary": row.get("summary") or "",
    "situation": row.get("situation") or "",
    "improved_behavior": row.get("improved_behavior") or "",
    "avoid": row.get("avoid") or "",
    "stack_tags": row.get("stack_tags") or "",
    "source_count": source_count,
    "confidence_score": float(row.get("confidence_score") or 0),
    "injected_into_agent_context": platform_pattern_injection_allowed(row, min_source_count=min_source_count),
    "promotion_status": promotion_status,
    "confidence_tier": metadata.get("confidence_tier") or promotion_status,
    "evidence_count": int(metadata.get("evidence_count") or source_count),
    "success_count": int(metadata.get("success_count") or 0),
    "failure_count": int(metadata.get("failure_count") or 0),
    "first_seen_at": row.get("first_seen_at"),
    "last_seen_at": row.get("last_seen_at"),
    "updated_at": row.get("updated_at"),
    "metadata": metadata,
  }


def list_platform_memory_patterns_payload(
  store: Any,
  *,
  domain: str | None = None,
  module: str | None = None,
  pattern_type: str | None = None,
  limit: int = 25,
) -> dict[str, Any]:
  if store is None or not hasattr(store, "list_memory_platform_patterns"):
    min_source_count = platform_pattern_min_source_count()
    return {
      "schema": "worktual.platform-memory-patterns.v1",
      "patterns": [],
      "stats": _empty_stats(min_source_count),
      "learning_rules": _learning_rules(min_source_count),
    }

  safe_limit = max(1, min(int(limit or 25), 50))
  rows = store.list_memory_platform_patterns(
    domain=str(domain).strip() if domain else None,
    module=str(module).strip() if module else None,
    pattern_type=str(pattern_type).strip() if pattern_type else None,
    limit=safe_limit,
  )
  min_source_count = platform_pattern_min_source_count()
  patterns = [serialize_platform_pattern(row, min_source_count=min_source_count) for row in rows if isinstance(row, dict)]
  domains = sorted({str(item.get("domain") or "general") for item in patterns})
  modules = sorted({str(item.get("module") or "general") for item in patterns})
  injectable = [item for item in patterns if item.get("injected_into_agent_context")]
  return {
    "schema": "worktual.platform-memory-patterns.v1",
    "patterns": patterns,
    "stats": {
      "listed": len(patterns),
      "injectable_listed": len(injectable),
      "domains_seen": domains,
      "modules_seen": modules,
      "min_source_count": min_source_count,
      "failed_run_learning_enabled": platform_failed_run_learning_enabled(),
    },
    "learning_rules": _learning_rules(min_source_count),
  }


def _empty_stats(min_source_count: int) -> dict[str, Any]:
  return {
    "listed": 0,
    "injectable_listed": 0,
    "domains_seen": [],
    "modules_seen": [],
    "min_source_count": min_source_count,
    "failed_run_learning_enabled": platform_failed_run_learning_enabled(),
  }


def _learning_rules(min_source_count: int) -> dict[str, Any]:
  return {
    "min_source_count": min_source_count,
    "env_var": "PLATFORM_PATTERN_MIN_SOURCE_COUNT",
    "failed_run_learning_env": "ENABLE_PLATFORM_FAILED_RUN_LEARNING",
    "failed_run_learning_enabled": platform_failed_run_learning_enabled(),
    "anonymized_only": True,
    "contains_chat": False,
  }
