"""Legacy memory_items episodic migration and read-path retirement."""

from __future__ import annotations

from typing import Any

from .episodic import (
  EPISODIC_KIND,
  EPISODIC_NAMESPACE,
  metadata_from_memory_row,
  should_write_episodic_episode,
)

try:
  from ..runtime_config import legacy_episodic_read_enabled
except ImportError:
  from agents.runtime_config import legacy_episodic_read_enabled


def list_legacy_episodic_items(
  store: Any,
  user: Any,
  *,
  project_id: str,
  fetch_limit: int,
) -> list[dict[str, Any]]:
  if not legacy_episodic_read_enabled():
    return []
  if not hasattr(store, "list_memory_items"):
    return []
  return store.list_memory_items(
    user,
    project_id=project_id,
    namespace=EPISODIC_NAMESPACE,
    kind=EPISODIC_KIND,
    limit=fetch_limit,
  )


def migrate_legacy_episodic_items_to_episodes(
  store: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str,
) -> dict[str, Any]:
  if not hasattr(store, "list_memory_items") or not hasattr(store, "insert_memory_episode"):
    return {"status": "skipped", "reason": "store_unavailable", "migrated": 0}

  legacy_rows = store.list_memory_items(
    user,
    project_id=project_id,
    namespace=EPISODIC_NAMESPACE,
    kind=EPISODIC_KIND,
    limit=100,
  )
  migrated = 0
  skipped = 0
  for row in legacy_rows:
    if not isinstance(row, dict):
      continue
    metadata = metadata_from_memory_row(row)
    row_session_id = str(metadata.get("chat_session_id") or chat_session_id or "").strip()
    if chat_session_id and row_session_id and row_session_id != chat_session_id:
      skipped += 1
      continue
    intent = str(metadata.get("intent") or "website_update")
    outcome = str(metadata.get("outcome") or "completed")
    changed_paths = metadata.get("changed_paths") if isinstance(metadata.get("changed_paths"), list) else []
    if not should_write_episodic_episode(
      intent=intent,
      outcome=outcome,
      changed_paths=changed_paths,
      error_category=str(metadata.get("error_category") or "") or None,
    ):
      skipped += 1
      continue
    generation_run_id = str(metadata.get("run_id") or metadata.get("generation_run_id") or "") or None
    if generation_run_id and hasattr(store, "find_memory_episode_by_run_id"):
      existing = store.find_memory_episode_by_run_id(
        user,
        project_id=project_id,
        chat_session_id=row_session_id or chat_session_id,
        generation_run_id=generation_run_id,
      )
      if existing:
        skipped += 1
        continue
    inserted = store.insert_memory_episode(
      user,
      project_id=project_id,
      chat_session_id=row_session_id or chat_session_id,
      generation_run_id=generation_run_id,
      scope="personal",
      memory_type="update_checkpoint",
      title=str(metadata.get("title") or f"Legacy episodic · {intent}")[:240],
      searchable_summary=str(row.get("content") or "")[:4000],
      situation=str(metadata.get("situation") or "")[:2000],
      improved_behavior=str(metadata.get("improved_behavior") or "")[:2000],
      avoid=str(metadata.get("avoid") or "")[:1200],
      outcome=outcome,
      changed_paths=changed_paths,
      metadata={
        **metadata,
        "source": "legacy_memory_items_migration",
        "legacy_key": row.get("key"),
        "intent": intent,
        "chat_session_id": row_session_id or chat_session_id,
      },
    )
    if isinstance(inserted, dict):
      try:
        from .episode_vector_sync import sync_episode_vector_from_row

        sync_episode_vector_from_row(
          inserted,
          user_id=str(user.id),
          project_id=project_id,
          chat_session_id=row_session_id or chat_session_id,
        )
      except Exception:
        pass
    migrated += 1

  return {
    "status": "completed",
    "migrated": migrated,
    "skipped": skipped,
    "legacy_rows_seen": len(legacy_rows),
  }
