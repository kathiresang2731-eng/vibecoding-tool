from __future__ import annotations

from typing import Any

from .episodic import tokenize_for_relevance


def score_platform_pattern(pattern: dict[str, Any], *, prompt: str, domain: str | None = None, modules: list[str] | None = None) -> float:
  prompt_tokens = tokenize_for_relevance(prompt)
  if not prompt_tokens:
    return 0.0
  module_tokens = tokenize_for_relevance(" ".join(modules or []))
  haystack = " ".join(
    [
      str(pattern.get("title") or ""),
      str(pattern.get("summary") or ""),
      str(pattern.get("domain") or ""),
      str(pattern.get("module") or ""),
      str(pattern.get("pattern_type") or ""),
      str(pattern.get("situation") or ""),
      str(pattern.get("improved_behavior") or ""),
    ]
  )
  pattern_tokens = tokenize_for_relevance(haystack)
  if not pattern_tokens:
    return 0.0
  overlap = len(prompt_tokens & pattern_tokens)
  score = overlap / max(len(prompt_tokens), 1)
  if domain and str(pattern.get("domain") or "").lower() == str(domain).lower():
    score += 0.35
  if modules and str(pattern.get("module") or "").lower() in {str(item).lower() for item in modules}:
    score += 0.2
  if module_tokens and pattern_tokens & module_tokens:
    score += 0.15
  source_count = int(pattern.get("source_count") or 0)
  if source_count >= 2:
    score += min(0.25, source_count * 0.05)
  return score


def rank_platform_patterns(
  patterns: list[dict[str, Any]],
  *,
  prompt: str,
  domain: str | None = None,
  modules: list[str] | None = None,
) -> list[dict[str, Any]]:
  if not patterns:
    return []
  scored = [
    (score_platform_pattern(item, prompt=prompt, domain=domain, modules=modules), item)
    for item in patterns
    if isinstance(item, dict)
  ]
  scored.sort(key=lambda pair: pair[0], reverse=True)
  return [item for _, item in scored]
