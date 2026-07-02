"""Episode vector index — Qdrant when configured, in-memory fallback for dev/tests."""

from __future__ import annotations

import math
import os
import threading
from typing import Any, Protocol

from .episode_embeddings import build_episode_embedding_text, embed_episode_text, embedding_vector_size

_STORE_LOCK = threading.Lock()
_STORE_INSTANCE: "EpisodeVectorStore | None" = None


class EpisodeVectorStore(Protocol):
  def upsert_episode(
    self,
    *,
    episode_id: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    searchable_summary: str,
    intent: str = "",
    outcome: str = "",
    changed_paths: list[str] | None = None,
    prompt: str = "",
  ) -> bool: ...

  def delete_episode(self, *, episode_id: str) -> bool: ...

  def search(
    self,
    *,
    query: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    limit: int = 8,
  ) -> list[dict[str, Any]]: ...


def qdrant_episode_search_enabled() -> bool:
  return os.getenv("WORKTUAL_QDRANT_URL", "").strip() != ""


def qdrant_collection_name() -> str:
  return os.getenv("WORKTUAL_QDRANT_EPISODES_COLLECTION", "worktual_memory_episodes").strip() or "worktual_memory_episodes"


def episodic_vector_search_enabled() -> bool:
  raw = os.getenv("ENABLE_EPISODIC_VECTOR_SEARCH", "").strip().lower()
  if raw in {"0", "false", "no", "off"}:
    return False
  if raw in {"1", "true", "yes", "on"}:
    return True
  return qdrant_episode_search_enabled() or episodic_vector_memory_fallback_enabled()


def episodic_vector_memory_fallback_enabled() -> bool:
  raw = os.getenv("ENABLE_EPISODIC_VECTOR_MEMORY_FALLBACK", "true").strip().lower()
  return raw not in {"0", "false", "no", "off"}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
  if not left or not right or len(left) != len(right):
    return 0.0
  dot = sum(a * b for a, b in zip(left, right))
  left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
  right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
  return dot / (left_norm * right_norm)


class InMemoryEpisodeVectorStore:
  def __init__(self) -> None:
    self._points: dict[str, dict[str, Any]] = {}
    self._lock = threading.Lock()

  def upsert_episode(
    self,
    *,
    episode_id: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    searchable_summary: str,
    intent: str = "",
    outcome: str = "",
    changed_paths: list[str] | None = None,
    prompt: str = "",
  ) -> bool:
    text = build_episode_embedding_text(
      searchable_summary=searchable_summary,
      intent=intent,
      outcome=outcome,
      changed_paths=changed_paths,
      prompt=prompt,
    )
    vector = embed_episode_text(text)
    with self._lock:
      self._points[str(episode_id)] = {
        "episode_id": str(episode_id),
        "user_id": str(user_id),
        "project_id": str(project_id),
        "chat_session_id": str(chat_session_id),
        "vector": vector,
      }
    return True

  def delete_episode(self, *, episode_id: str) -> bool:
    with self._lock:
      return self._points.pop(str(episode_id), None) is not None

  def search(
    self,
    *,
    query: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    limit: int = 8,
  ) -> list[dict[str, Any]]:
    query_vector = embed_episode_text(str(query or "").strip())
    scored: list[tuple[float, dict[str, Any]]] = []
    with self._lock:
      points = list(self._points.values())
    for point in points:
      if point.get("user_id") != str(user_id):
        continue
      if point.get("project_id") != str(project_id):
        continue
      if point.get("chat_session_id") != str(chat_session_id):
        continue
      score = _cosine_similarity(query_vector, list(point.get("vector") or []))
      if score <= 0:
        continue
      scored.append((score, {"episode_id": point["episode_id"], "score": score, "engine": "memory_vector"}))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[: max(1, limit)]]


class QdrantEpisodeVectorStore:
  def __init__(self, *, url: str, api_key: str = "", collection_name: str | None = None) -> None:
    self.url = url.rstrip("/")
    self.api_key = api_key.strip()
    self.collection_name = collection_name or qdrant_collection_name()
    self._client = None
    self._vector_size: int | None = None

  def _get_client(self) -> Any:
    if self._client is not None:
      return self._client
    try:
      from qdrant_client import QdrantClient
    except ImportError as exc:
      raise RuntimeError("qdrant-client is required when WORKTUAL_QDRANT_URL is configured.") from exc
    kwargs: dict[str, Any] = {"url": self.url}
    if self.api_key:
      kwargs["api_key"] = self.api_key
    self._client = QdrantClient(**kwargs)
    return self._client

  def _ensure_collection(self, vector_size: int) -> None:
    from qdrant_client.models import Distance, VectorParams

    client = self._get_client()
    if client.collection_exists(self.collection_name):
      return
    client.create_collection(
      collection_name=self.collection_name,
      vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

  def upsert_episode(
    self,
    *,
    episode_id: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    searchable_summary: str,
    intent: str = "",
    outcome: str = "",
    changed_paths: list[str] | None = None,
    prompt: str = "",
  ) -> bool:
    from qdrant_client.models import PointStruct

    text = build_episode_embedding_text(
      searchable_summary=searchable_summary,
      intent=intent,
      outcome=outcome,
      changed_paths=changed_paths,
      prompt=prompt,
    )
    vector = embed_episode_text(text)
    self._vector_size = len(vector)
    self._ensure_collection(len(vector))
    client = self._get_client()
    client.upsert(
      collection_name=self.collection_name,
      points=[
        PointStruct(
          id=str(episode_id),
          vector=vector,
          payload={
            "episode_id": str(episode_id),
            "user_id": str(user_id),
            "project_id": str(project_id),
            "chat_session_id": str(chat_session_id),
            "intent": intent,
            "outcome": outcome,
          },
        )
      ],
    )
    return True

  def delete_episode(self, *, episode_id: str) -> bool:
    client = self._get_client()
    if not client.collection_exists(self.collection_name):
      return False
    client.delete(collection_name=self.collection_name, points_selector=[str(episode_id)])
    return True

  def search(
    self,
    *,
    query: str,
    user_id: str,
    project_id: str,
    chat_session_id: str,
    limit: int = 8,
  ) -> list[dict[str, Any]]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = self._get_client()
    if not client.collection_exists(self.collection_name):
      return []
    query_vector = embed_episode_text(str(query or "").strip())
    hits = client.search(
      collection_name=self.collection_name,
      query_vector=query_vector,
      limit=max(1, min(limit, 20)),
      query_filter=Filter(
        must=[
          FieldCondition(key="user_id", match=MatchValue(value=str(user_id))),
          FieldCondition(key="project_id", match=MatchValue(value=str(project_id))),
          FieldCondition(key="chat_session_id", match=MatchValue(value=str(chat_session_id))),
        ]
      ),
    )
    results: list[dict[str, Any]] = []
    for hit in hits:
      payload = hit.payload if isinstance(hit.payload, dict) else {}
      episode_id = str(payload.get("episode_id") or hit.id or "")
      if not episode_id:
        continue
      results.append(
        {
          "episode_id": episode_id,
          "score": float(hit.score or 0.0),
          "engine": "qdrant",
        }
      )
    return results


def get_episode_vector_store() -> EpisodeVectorStore | None:
  global _STORE_INSTANCE
  if not episodic_vector_search_enabled():
    return None
  with _STORE_LOCK:
    if _STORE_INSTANCE is not None:
      return _STORE_INSTANCE
    if qdrant_episode_search_enabled():
      _STORE_INSTANCE = QdrantEpisodeVectorStore(
        url=os.getenv("WORKTUAL_QDRANT_URL", "").strip(),
        api_key=os.getenv("WORKTUAL_QDRANT_API_KEY", "").strip(),
      )
    elif episodic_vector_memory_fallback_enabled():
      _STORE_INSTANCE = InMemoryEpisodeVectorStore()
    else:
      _STORE_INSTANCE = None
    return _STORE_INSTANCE


def reset_episode_vector_store_for_tests() -> None:
  global _STORE_INSTANCE
  with _STORE_LOCK:
    _STORE_INSTANCE = None


def search_episode_vectors(
  *,
  query: str,
  user_id: str,
  project_id: str,
  chat_session_id: str,
  limit: int = 8,
) -> list[dict[str, Any]]:
  store = get_episode_vector_store()
  if store is None or not str(query or "").strip():
    return []
  try:
    return store.search(
      query=query,
      user_id=user_id,
      project_id=project_id,
      chat_session_id=chat_session_id,
      limit=limit,
    )
  except Exception:
    return []


def index_episode_vector(
  *,
  episode_id: str,
  user_id: str,
  project_id: str,
  chat_session_id: str,
  searchable_summary: str,
  intent: str = "",
  outcome: str = "",
  changed_paths: list[str] | None = None,
  prompt: str = "",
) -> bool:
  store = get_episode_vector_store()
  if store is None or not episode_id:
    return False
  try:
    return store.upsert_episode(
      episode_id=str(episode_id),
      user_id=str(user_id),
      project_id=str(project_id),
      chat_session_id=str(chat_session_id),
      searchable_summary=searchable_summary,
      intent=intent,
      outcome=outcome,
      changed_paths=changed_paths,
      prompt=prompt,
    )
  except Exception:
    return False


def delete_episode_vector(*, episode_id: str) -> bool:
  store = get_episode_vector_store()
  if store is None or not episode_id:
    return False
  try:
    return store.delete_episode(episode_id=str(episode_id))
  except Exception:
    return False
