"""Hybrid episodic retrieval — token overlap + semantic-like phrase/path matching."""

from __future__ import annotations

import re
from typing import Any

from .episodic import metadata_from_memory_row, score_episodic_relevance, tokenize_for_relevance

_PHRASE_SPLIT = re.compile(r"[^a-z0-9]+")
_PATH_STEM = re.compile(r"[a-z0-9]+")
SEMANTIC_WEIGHT = 0.6
TOKEN_WEIGHT = 0.4
VECTOR_WEIGHT = 0.35
HYBRID_BLEND_WEIGHT = 0.65


def episodic_ranking_weights() -> dict[str, float]:
  return {
    "semantic": SEMANTIC_WEIGHT,
    "token_overlap": TOKEN_WEIGHT,
    "vector": VECTOR_WEIGHT,
    "hybrid_blend": HYBRID_BLEND_WEIGHT,
  }


def episodic_hybrid_weights() -> tuple[float, float]:
  return SEMANTIC_WEIGHT, TOKEN_WEIGHT


def _episode_haystack(memory: dict[str, Any]) -> str:
  metadata = metadata_from_memory_row(memory)
  changed_paths = metadata.get("changed_paths") if isinstance(metadata.get("changed_paths"), list) else []
  return " ".join(
    [
      str(memory.get("content") or ""),
      str(metadata.get("intent") or ""),
      str(metadata.get("outcome") or ""),
      str(metadata.get("prompt") or ""),
      " ".join(str(path) for path in changed_paths),
    ]
  ).lower()


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
  if len(tokens) < 2:
    return set()
  return {(tokens[index], tokens[index + 1]) for index in range(len(tokens) - 1)}


def _jaccard(left: set[str] | set[tuple[str, str]], right: set[str] | set[tuple[str, str]]) -> float:
  if not left or not right:
    return 0.0
  overlap = len(left & right)
  return overlap / max(len(left | right), 1)


def _path_stems(changed_paths: list[str] | None) -> set[str]:
  stems: set[str] = set()
  for path in changed_paths or []:
    base = str(path).rsplit("/", 1)[-1].lower()
    name = base.rsplit(".", 1)[0]
    for token in _PATH_STEM.findall(name):
      if len(token) >= 3:
        stems.add(token)
  return stems


def _phrase_overlap_score(prompt: str, haystack: str) -> float:
  words = [word for word in _PHRASE_SPLIT.findall(prompt.lower()) if len(word) >= 3]
  if len(words) < 2:
    return 0.0
  hits = 0
  attempts = 0
  for size in (4, 3, 2):
    for index in range(0, max(len(words) - size + 1, 0)):
      phrase = " ".join(words[index : index + size])
      attempts += 1
      if phrase and phrase in haystack:
        hits += size
  if attempts == 0:
    return 0.0
  return min(1.0, hits / max(len(words), 1))


def score_episodic_semantic(memory: dict[str, Any], prompt: str) -> float:
  prompt_text = str(prompt or "").strip().lower()
  if not prompt_text:
    return 0.0
  haystack = _episode_haystack(memory)
  if not haystack.strip():
    return 0.0

  prompt_tokens = sorted(tokenize_for_relevance(prompt_text))
  memory_tokens = sorted(tokenize_for_relevance(haystack))
  token_jaccard = _jaccard(set(prompt_tokens), set(memory_tokens))
  bigram_jaccard = _jaccard(_bigrams(prompt_tokens), _bigrams(memory_tokens))
  phrase_score = _phrase_overlap_score(prompt_text, haystack)

  metadata = metadata_from_memory_row(memory)
  changed_paths = metadata.get("changed_paths") if isinstance(metadata.get("changed_paths"), list) else []
  path_score = 0.0
  path_stems = _path_stems(changed_paths)
  if path_stems:
    prompt_token_set = set(prompt_tokens)
    path_score = len(path_stems & prompt_token_set) / max(len(path_stems), 1)

  semantic = max(
    token_jaccard,
    bigram_jaccard * 1.15,
    phrase_score,
    path_score * 0.9,
  )
  return min(1.0, semantic)


def score_episodic_hybrid(memory: dict[str, Any], prompt: str) -> float:
  semantic = score_episodic_semantic(memory, prompt)
  token_overlap = score_episodic_relevance(memory, prompt)
  semantic_weight, token_weight = episodic_hybrid_weights()
  return min(1.0, semantic_weight * semantic + token_weight * token_overlap)


def rank_episodic_memories_hybrid(
  memories: list[dict[str, Any]],
  *,
  prompt: str = "",
) -> list[dict[str, Any]]:
  if not memories:
    return []
  if not str(prompt or "").strip():
    return list(memories)

  def sort_key(item: dict[str, Any]) -> tuple[float, str]:
    return (score_episodic_hybrid(item, prompt), str(item.get("updated_at") or ""))

  return sorted(memories, key=sort_key, reverse=True)


def rank_episodic_memories_with_vector(
  memories: list[dict[str, Any]],
  *,
  prompt: str = "",
  vector_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
  if not memories:
    return []
  if not str(prompt or "").strip():
    return list(memories)
  scores = vector_scores or {}
  if not scores:
    return rank_episodic_memories_hybrid(memories, prompt=prompt)

  def sort_key(item: dict[str, Any]) -> tuple[float, str]:
    episode_id = str(item.get("id") or "")
    hybrid = score_episodic_hybrid(item, prompt)
    vector = float(scores.get(episode_id) or 0.0)
    combined = HYBRID_BLEND_WEIGHT * hybrid + VECTOR_WEIGHT * vector
    return (combined, str(item.get("updated_at") or ""))

  return sorted(memories, key=sort_key, reverse=True)


def qdrant_episode_search_enabled() -> bool:
  try:
    from .episode_vector_store import qdrant_episode_search_enabled as _enabled

    return _enabled()
  except ImportError:
    from agents.memory.episode_vector_store import qdrant_episode_search_enabled as _enabled

    return _enabled()


def search_episodes_via_qdrant(
  *,
  query: str,
  user_id: str,
  project_id: str,
  chat_session_id: str,
  limit: int = 5,
) -> list[dict[str, Any]]:
  try:
    from .episode_vector_store import search_episode_vectors
  except ImportError:
    from agents.memory.episode_vector_store import search_episode_vectors

  return search_episode_vectors(
    query=query,
    user_id=user_id,
    project_id=project_id,
    chat_session_id=chat_session_id,
    limit=limit,
  )
