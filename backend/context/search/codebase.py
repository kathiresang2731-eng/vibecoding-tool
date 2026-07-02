from __future__ import annotations

import re
from typing import Any

from .index import InMemoryCodeIndex, build_code_index, qdrant_index_enabled


MAX_MATCHES = 50
MAX_SNIPPET_CHARS = 240


def search_project_codebase(
  files: list[dict[str, Any]] | None,
  *,
  query: str,
  limit: int = 20,
  index: InMemoryCodeIndex | None = None,
) -> dict[str, Any]:
  """Search project files via in-memory index when available, else exact scan."""
  cleaned_query = str(query or "").strip()
  if not cleaned_query:
    return {"query": "", "match_count": 0, "matches": [], "status": "empty_query"}

  if index is None and files:
    index = build_code_index(files)
  if index is not None and index.search(cleaned_query, limit=limit):
    matches = index.search(cleaned_query, limit=limit)
    return {
      "query": cleaned_query,
      "match_count": len(matches),
      "matches": matches,
      "status": "completed",
      "engine": "memory_index",
      "qdrant_enabled": qdrant_index_enabled(),
    }

  pattern = None
  if cleaned_query.startswith("/") and cleaned_query.endswith("/") and len(cleaned_query) > 2:
    try:
      pattern = re.compile(cleaned_query[1:-1], re.IGNORECASE)
    except re.error:
      pattern = None

  needle = cleaned_query.lower()
  matches: list[dict[str, Any]] = []
  for item in files or []:
    if not isinstance(item, dict):
      continue
    path = str(item.get("path") or "").strip()
    content = str(item.get("content") or "")
    if not path:
      continue
    if needle in path.lower():
      matches.append({"path": path, "line": 0, "snippet": path, "match_type": "path"})
      if len(matches) >= min(limit, MAX_MATCHES):
        break
    for lineno, line in enumerate(content.splitlines(), start=1):
      haystack = line
      if pattern is not None:
        found = pattern.search(haystack)
        if not found:
          continue
      elif needle not in haystack.lower():
        continue
      matches.append(
        {
          "path": path,
          "line": lineno,
          "snippet": haystack.strip()[:MAX_SNIPPET_CHARS],
          "match_type": "content",
        }
      )
      if len(matches) >= min(limit, MAX_MATCHES):
        break
    if len(matches) >= min(limit, MAX_MATCHES):
      break

  return {
    "query": cleaned_query,
    "match_count": len(matches),
    "matches": matches[: min(limit, MAX_MATCHES)],
    "status": "completed",
    "engine": "exact_scaffold",
  }
