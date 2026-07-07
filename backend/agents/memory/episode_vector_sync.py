"""Sync episodic rows into the vector index."""

from __future__ import annotations

from typing import Any

from .episode_vector_store import delete_episode_vector, index_episode_vector


def _episode_fields_from_row(row: dict[str, Any]) -> dict[str, Any]:
  metadata = row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {}
  if not metadata and isinstance(row.get("metadata"), dict):
    metadata = row["metadata"]
  changed_paths = row.get("changed_paths_json")
  if not isinstance(changed_paths, list):
    changed_paths = metadata.get("changed_paths") if isinstance(metadata.get("changed_paths"), list) else []
  return {
    "episode_id": str(row.get("id") or ""),
    "searchable_summary": str(row.get("searchable_summary") or row.get("content") or ""),
    "intent": str(metadata.get("intent") or row.get("memory_type") or ""),
    "outcome": str(row.get("outcome") or metadata.get("outcome") or "completed"),
    "changed_paths": changed_paths if isinstance(changed_paths, list) else [],
    "prompt": str(metadata.get("prompt") or ""),
  }


def sync_episode_vector_from_row(
  row: dict[str, Any],
  *,
  user_id: str,
  project_id: str,
  chat_session_id: str,
) -> bool:
  fields = _episode_fields_from_row(row)
  if not fields["episode_id"]:
    return False
  return index_episode_vector(
    episode_id=fields["episode_id"],
    user_id=user_id,
    project_id=project_id,
    chat_session_id=chat_session_id,
    searchable_summary=fields["searchable_summary"],
    intent=fields["intent"],
    outcome=fields["outcome"],
    changed_paths=fields["changed_paths"],
    prompt=fields["prompt"],
  )


def remove_episode_vector(*, episode_id: str) -> bool:
  return delete_episode_vector(episode_id=episode_id)
