from __future__ import annotations

from typing import Any

try:
  from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
except ImportError:
  from backend.agents.memory.session_monitor import persist_generation_memory_checkpoint
try:
  from backend.agents.memory.topic_clustering import filter_chat_messages_for_topic
except ImportError:
  from agents.memory.topic_clustering import filter_chat_messages_for_topic

from backend.storage import UserContext


def _compatibility_export(name: str, fallback: Any) -> Any:
  try:
    from backend import main as main_facade

    return getattr(main_facade, name, fallback)
  except Exception:
    return fallback


def _list_project_chat_messages_compat(
  store: Any,
  project_id: str,
  user: UserContext,
  *,
  limit: int,
  chat_session_id: str | None,
  chat_topic_id: str | None = None,
) -> list[dict[str, Any]]:
  if not hasattr(store, "list_project_chat_messages"):
    return []
  try:
    return store.list_project_chat_messages(
      project_id,
      user,
      limit=limit,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
    )
  except TypeError as exc:
    if "chat_topic_id" in str(exc):
      messages = store.list_project_chat_messages(project_id, user, limit=limit, chat_session_id=chat_session_id)
      return filter_chat_messages_for_topic(messages, chat_topic_id=chat_topic_id, max_messages=limit)
    if "chat_session_id" not in str(exc):
      raise
    messages = store.list_project_chat_messages(project_id, user, limit=limit)
    return filter_chat_messages_for_topic(messages, chat_topic_id=chat_topic_id, max_messages=limit)


def _record_project_chat_message_compat(
  store: Any,
  project_id: str,
  user: UserContext,
  *,
  role: str,
  content: str,
  metadata: dict[str, Any] | None = None,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
) -> Any:
  if not hasattr(store, "record_project_chat_message"):
    return None
  metadata_payload = dict(metadata or {})
  if chat_topic_id:
    metadata_payload["chat_topic_id"] = chat_topic_id
  try:
    return store.record_project_chat_message(
      project_id,
      user,
      role=role,
      content=content,
      metadata=metadata_payload,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
    )
  except TypeError as exc:
    if "chat_topic_id" in str(exc):
      return store.record_project_chat_message(
        project_id,
        user,
        role=role,
        content=content,
        metadata=metadata_payload,
        chat_session_id=chat_session_id,
      )
    if "chat_session_id" not in str(exc):
      raise
    return store.record_project_chat_message(project_id, user, role=role, content=content, metadata=metadata_payload)


def _persist_memory_checkpoint_safe(
  store: Any,
  user: UserContext,
  *,
  project_id: str,
  chat_session_id: str | None,
  generation_run_id: str | None,
  prompt: str,
  intent: str,
  outcome: str,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  changed_paths: list[str] | None = None,
  preview_status: str | None = None,
  error_category: str | None = None,
  chat_topic_id: str | None = None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  try:
    return persist_generation_memory_checkpoint(
      store,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
      prompt=prompt,
      intent=intent,
      outcome=outcome,
      project_name=project_name,
      files=files,
      changed_paths=changed_paths,
      preview_status=preview_status,
      error_category=error_category,
      chat_topic_id=chat_topic_id,
      extra=extra,
    )
  except Exception:
    return {"status": "skipped", "reason": "persist_failed"}
