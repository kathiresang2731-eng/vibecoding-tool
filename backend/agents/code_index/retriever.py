from __future__ import annotations

import math
from typing import Any

try:
  from ..memory.episodic import tokenize_for_relevance
  from ..memory.episode_embeddings import embed_episode_text
except ImportError:
  from agents.memory.episodic import tokenize_for_relevance
  from agents.memory.episode_embeddings import embed_episode_text

from .indexer import chunk_file
from .store import get_project_chunks, set_project_chunks, upsert_file_chunks


def _cosine_similarity(a: list[float], b: list[float]) -> float:
  if not a or not b:
    return 0.0
  size = min(len(a), len(b))
  dot = sum(a[i] * b[i] for i in range(size))
  norm_a = math.sqrt(sum(value * value for value in a[:size])) or 1.0
  norm_b = math.sqrt(sum(value * value for value in b[:size])) or 1.0
  return dot / (norm_a * norm_b)


def _lexical_score(query: str, *, path: str, content: str) -> tuple[float, list[str]]:
  tokens = tokenize_for_relevance(query)
  if not tokens:
    return 0.0, []
  lowered_path = path.lower()
  lowered_content = content.lower()
  matched = [token for token in tokens if token in lowered_path or token in lowered_content]
  if not matched:
    return 0.0, []
  return min(1.0, len(matched) / max(1, len(tokens))), matched


def retrieve_code_context(
  query: str,
  files: list[dict[str, str]],
  *,
  project_id: str = "",
  limit: int = 12,
) -> list[dict[str, Any]]:
  """Hybrid retrieval: project index when warm, else lexical scan over files."""
  chunks = get_project_chunks(project_id) if project_id else []
  if not chunks:
    from .indexer import chunk_project_files

    chunks = chunk_project_files(files, project_id=project_id)
    if project_id and chunks:
      set_project_chunks(project_id, [
        {**chunk, "embedding": embed_episode_text(f"{chunk['path']} {chunk.get('symbol', '')} {chunk.get('content', '')[:1500]}")}
        for chunk in chunks
      ])

  query_embedding = embed_episode_text(query)
  scored: list[tuple[float, dict[str, Any]]] = []
  for chunk in chunks:
    path = str(chunk.get("path") or "")
    content = str(chunk.get("content") or "")
    lex_score, matched = _lexical_score(query, path=path, content=content)
    vec_score = _cosine_similarity(query_embedding, list(chunk.get("embedding") or []))
    score = (vec_score * 0.55) + (lex_score * 0.45)
    if score <= 0:
      continue
    snippet = content[:2400]
    scored.append(
      (
        score,
        {
          "path": path,
          "symbol": str(chunk.get("symbol") or ""),
          "line_start": int(chunk.get("line_start") or 0),
          "line_end": int(chunk.get("line_end") or 0),
          "score": round(score, 4),
          "matched_terms": matched[:8],
          "snippets": [snippet] if snippet else [],
          "content_chars": len(content),
        },
      )
    )

  if not scored and files:
    return _grep_code_search_matches(query, files, limit=limit)

  scored.sort(key=lambda item: (-item[0], item[1]["path"]))
  results = [item[1] for item in scored[:limit]]
  if results:
    return results
  return _grep_code_search_matches(query, files, limit=limit)


def _grep_code_search_matches(query: str, files: list[dict[str, str]], *, limit: int = 12) -> list[dict[str, Any]]:
  try:
    from ..agent_runtime.update_analysis import (
      code_match_snippet,
      extract_update_search_terms,
      interaction_render_context_snippets,
      unique_snippets,
    )
  except ImportError:
    from agents.agent_runtime.update_analysis import (
      code_match_snippet,
      extract_update_search_terms,
      interaction_render_context_snippets,
      unique_snippets,
    )
  terms = extract_update_search_terms(query)
  matches: list[dict[str, Any]] = []
  for file_item in files:
    path = file_item["path"]
    content = file_item["content"]
    if not path.endswith((".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".json")):
      continue
    lowered_content = content.lower()
    matched_terms = [term for term in terms if term.lower() in lowered_content or term.lower() in path.lower()]
    if not matched_terms:
      continue
    snippets: list[str] = []
    for term in matched_terms[:3]:
      snippet = code_match_snippet(content, term)
      if snippet:
        snippets.append(snippet)
    snippets.extend(interaction_render_context_snippets(content, terms=terms))
    matches.append(
      {
        "path": path,
        "matched_terms": matched_terms[:8],
        "snippets": unique_snippets(snippets, max_count=6, max_chars_each=2400),
        "content_chars": len(content),
      }
    )
  return matches[:limit]


def index_files(
  project_id: str,
  files: list[dict[str, str]],
  *,
  paths: list[str] | None = None,
) -> int:
  """Incrementally index only the given paths (or all files)."""
  path_filter = set(paths or [])
  indexed = 0
  for item in files:
    path = str(item.get("path") or "")
    content = str(item.get("content") or "")
    if not path:
      continue
    if path_filter and path not in path_filter:
      continue
    chunks = chunk_file(path, content, project_id=project_id)
    if chunks:
      upsert_file_chunks(project_id, path, chunks)
      indexed += 1
  return indexed
