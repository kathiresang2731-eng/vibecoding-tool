from __future__ import annotations

import hashlib
from typing import Any


class InMemoryCodeIndex:
  """Lightweight in-memory code index. Qdrant integration is optional in Phase 2."""

  def __init__(self) -> None:
    self._chunks: list[dict[str, Any]] = []

  def build_from_files(self, files: list[dict[str, Any]] | None) -> int:
    self._chunks = []
    for item in files or []:
      if not isinstance(item, dict):
        continue
      path = str(item.get("path") or "").strip()
      content = str(item.get("content") or "")
      if not path or not content.strip():
        continue
      for lineno, line in enumerate(content.splitlines(), start=1):
        snippet = line.strip()
        if not snippet:
          continue
        digest = hashlib.sha1(f"{path}:{lineno}:{snippet}".encode("utf-8")).hexdigest()[:12]
        self._chunks.append(
          {
            "id": digest,
            "path": path,
            "line": lineno,
            "snippet": snippet[:240],
            "text": snippet.lower(),
          }
        )
    return len(self._chunks)

  def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    needle = str(query or "").strip().lower()
    if not needle:
      return []
    matches: list[dict[str, Any]] = []
    for chunk in self._chunks:
      if needle in chunk["text"] or needle in chunk["path"].lower():
        matches.append(
          {
            "path": chunk["path"],
            "line": chunk["line"],
            "snippet": chunk["snippet"],
            "match_type": "index",
            "chunk_id": chunk["id"],
          }
        )
      if len(matches) >= limit:
        break
    return matches


def qdrant_index_enabled() -> bool:
  import os

  return os.getenv("WORKTUAL_QDRANT_URL", "").strip() != ""


def build_code_index(files: list[dict[str, Any]] | None) -> InMemoryCodeIndex:
  index = InMemoryCodeIndex()
  index.build_from_files(files)
  return index
