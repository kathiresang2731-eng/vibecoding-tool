from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .episodic import (
  MAX_EPISODIC_ITEMS,
  episode_to_memory_row,
  select_episodic_memories_for_prompt,
  serialize_episodic_memory_for_api,
)

try:
  from ...storage import StorageError
except ImportError:
  from storage import StorageError


def _require_project(store: Any, project_id: str, user: Any) -> dict[str, Any]:
  if not hasattr(store, "get_project"):
    raise HTTPException(status_code=501, detail="Project store is unavailable.")
  project = store.get_project(project_id, user)
  if not project:
    raise HTTPException(status_code=404, detail="Project not found.")
  return project


def serialize_memory_episode(row: dict[str, Any], *, injected_into_agent_context: bool = False) -> dict[str, Any]:
  payload = serialize_episodic_memory_for_api(row)
  metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
  return {
    **payload,
    "memory_type": metadata.get("memory_type") or metadata.get("source") or payload.get("intent") or "",
    "searchable_summary": payload.get("content") or "",
    "title": metadata.get("title") or "",
    "injected_into_agent_context": injected_into_agent_context,
  }


def serialize_session_memory_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
  if not isinstance(state, dict):
    return None
  metadata = state.get("metadata_json") if isinstance(state.get("metadata_json"), dict) else {}
  if not metadata and isinstance(state.get("metadata"), dict):
    metadata = state["metadata"]
  changed_paths = state.get("last_changed_paths_json") or state.get("changed_paths") or []
  return {
    "chat_session_id": state.get("chat_session_id"),
    "rolling_summary": state.get("rolling_summary") or "",
    "update_count": int(state.get("update_count") or 0),
    "last_preview_status": state.get("last_preview_status"),
    "last_error_category": state.get("last_error_category"),
    "last_changed_paths": changed_paths if isinstance(changed_paths, list) else [],
    "file_count": int(state.get("file_count") or 0),
    "last_generation_run_id": state.get("last_generation_run_id"),
    "metadata": metadata,
    "updated_at": state.get("updated_at"),
  }


def list_memory_episodes_payload(
  user: Any,
  store: Any,
  *,
  project_id: str,
  chat_session_id: str,
  prompt: str = "",
  limit: int = MAX_EPISODIC_ITEMS,
) -> dict[str, Any]:
  normalized_project_id = str(project_id or "").strip()
  normalized_session_id = str(chat_session_id or "").strip()
  if not normalized_project_id or not normalized_session_id:
    raise HTTPException(status_code=400, detail="project_id and chat_session_id are required.")

  _require_project(store, normalized_project_id, user)
  if not hasattr(store, "list_memory_episodes"):
    return {
      "schema": "worktual.memory-episodes.v1",
      "project_id": normalized_project_id,
      "chat_session_id": normalized_session_id,
      "episodes": [],
      "session_memory_state": None,
      "injection_rules": _injection_rules(),
    }

  safe_limit = max(1, min(int(limit or MAX_EPISODIC_ITEMS), MAX_EPISODIC_ITEMS))
  selected = select_episodic_memories_for_prompt(
    store,
    user,
    project_id=normalized_project_id,
    prompt=prompt,
    chat_session_id=normalized_session_id,
    limit=safe_limit,
  )
  injected_ids = {str(item.get("id") or "") for item in selected if item.get("id")}

  rows = store.list_memory_episodes(
    user,
    project_id=normalized_project_id,
    chat_session_id=normalized_session_id,
    scope="personal",
    limit=max(safe_limit, 12),
  )
  episodes = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    adapted = episode_to_memory_row(row)
    episode_id = str(adapted.get("id") or row.get("id") or "")
    episodes.append(
      serialize_memory_episode(
        adapted,
        injected_into_agent_context=bool(episode_id and episode_id in injected_ids),
      )
    )

  session_state = None
  if hasattr(store, "get_memory_chat_session_state"):
    session_state = serialize_session_memory_state(
      store.get_memory_chat_session_state(user, chat_session_id=normalized_session_id)
    )

  return {
    "schema": "worktual.memory-episodes.v1",
    "project_id": normalized_project_id,
    "chat_session_id": normalized_session_id,
    "episodes": episodes,
    "session_memory_state": session_state,
    "injection_rules": _injection_rules(),
  }


def delete_memory_episode_payload(
  user: Any,
  store: Any,
  *,
  episode_id: str,
  project_id: str,
) -> dict[str, Any]:
  normalized_episode_id = str(episode_id or "").strip()
  normalized_project_id = str(project_id or "").strip()
  if not normalized_episode_id:
    raise HTTPException(status_code=400, detail="episode_id is required.")
  if not normalized_project_id:
    raise HTTPException(status_code=400, detail="project_id is required.")

  _require_project(store, normalized_project_id, user)
  if not hasattr(store, "delete_memory_episode"):
    raise HTTPException(status_code=501, detail="Memory episodes are not available on this store.")

  try:
    deleted = store.delete_memory_episode(
      user,
      episode_id=normalized_episode_id,
      project_id=normalized_project_id,
    )
  except StorageError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  if not deleted:
    raise HTTPException(status_code=404, detail="Episode not found.")
  try:
    from .episode_vector_sync import remove_episode_vector

    remove_episode_vector(episode_id=normalized_episode_id)
  except Exception:
    pass
  return {"deleted": True, "id": normalized_episode_id, "project_id": normalized_project_id}


def _injection_rules() -> dict[str, Any]:
  try:
    from ..runtime_config import (
      episodic_hybrid_retrieval_enabled,
      episodic_vector_search_enabled,
      legacy_episodic_read_enabled,
      qdrant_episode_search_enabled,
    )
  except ImportError:
    from agents.runtime_config import (
      episodic_hybrid_retrieval_enabled,
      episodic_vector_search_enabled,
      legacy_episodic_read_enabled,
      qdrant_episode_search_enabled,
    )

  semantic_weight, token_weight = (0.6, 0.4)
  vector_weight = 0.35
  hybrid_blend_weight = 0.65
  try:
    from .episode_retrieval import episodic_hybrid_weights, episodic_ranking_weights

    semantic_weight, token_weight = episodic_hybrid_weights()
    ranking_weights = episodic_ranking_weights()
    vector_weight = float(ranking_weights.get("vector") or vector_weight)
    hybrid_blend_weight = float(ranking_weights.get("hybrid_blend") or hybrid_blend_weight)
  except ImportError:
    pass

  ranking = "hybrid semantic + token overlap within the active chat session"
  if episodic_vector_search_enabled():
    ranking = "hybrid + vector similarity within the active chat session"

  return {
    "scope": "chat_session_id",
    "max_injected_episodes": MAX_EPISODIC_ITEMS,
    "ranking": ranking,
    "hybrid_retrieval_enabled": episodic_hybrid_retrieval_enabled(),
    "hybrid_weights": {"semantic": semantic_weight, "token_overlap": token_weight},
    "vector_retrieval_enabled": episodic_vector_search_enabled(),
    "vector_weights": {"vector": vector_weight, "hybrid_blend": hybrid_blend_weight},
    "qdrant_episode_search": qdrant_episode_search_enabled(),
    "legacy_episodic_read_enabled": legacy_episodic_read_enabled(),
    "note": "Session rolling summary may dedupe overlapping episodic text in the agent prompt.",
  }
