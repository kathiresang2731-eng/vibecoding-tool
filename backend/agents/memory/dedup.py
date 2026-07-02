from __future__ import annotations

import re
from typing import Any

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")


def _tokenize(text: str) -> set[str]:
  return set(_TOKEN_PATTERN.findall(str(text or "").lower()))


def token_overlap_ratio(left: str, right: str) -> float:
  left_tokens = _tokenize(left)
  right_tokens = _tokenize(right)
  if not left_tokens or not right_tokens:
    return 0.0
  overlap = len(left_tokens & right_tokens)
  return overlap / max(len(left_tokens), len(right_tokens))


def blocks_are_redundant(primary: str, secondary: str, *, threshold: float = 0.72) -> bool:
  """True when secondary content largely repeats primary (skip to save tokens)."""
  if not primary.strip() or not secondary.strip():
    return False
  return token_overlap_ratio(primary, secondary) >= threshold


def dedupe_memory_blocks(blocks: list[str], *, threshold: float = 0.72) -> list[str]:
  """Drop later blocks that substantially repeat earlier ones."""
  kept: list[str] = []
  for block in blocks:
    text = str(block or "").strip()
    if not text:
      continue
    if any(blocks_are_redundant(existing, text, threshold=threshold) for existing in kept):
      continue
    kept.append(text)
  return kept


def recent_chat_text(chat_messages: list[dict[str, Any]] | None, *, limit: int = 6) -> str:
  if not chat_messages:
    return ""
  parts: list[str] = []
  for item in chat_messages[-limit:]:
    if not isinstance(item, dict):
      continue
    role = str(item.get("role") or "")
    content = str(item.get("content") or item.get("display_content") or "").strip()
    if content:
      parts.append(f"{role}: {content}")
  return "\n".join(parts)
