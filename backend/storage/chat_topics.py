from __future__ import annotations

from typing import Any

from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_memory_scope, require_project
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext


def _bounded_confidence(value: float | int | str | None, default: float = 0.6) -> float:
  try:
    parsed = float(value if value is not None else default)
  except (TypeError, ValueError):
    parsed = default
  return max(0.0, min(0.999, parsed))


class ChatTopicStoreMixin:
  def create_memory_chat_topic(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    label: str,
    intent_family: str = "general",
    memory_scope: str = "topic",
    topic_tags: str = "",
    rolling_summary: str = "",
    related_paths: list[str] | None = None,
    related_modules: list[str] | None = None,
    last_prompt: str = "",
    last_changed_paths: list[str] | None = None,
    confidence: float = 0.6,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    require_memory_scope(
      self,
      user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      write=True,
    )
    topic_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into memory_chat_topics (
            id, project_id, user_id, chat_session_id, label, intent_family, memory_scope,
            topic_tags, rolling_summary, related_paths_json, related_modules_json,
            last_prompt, last_changed_paths_json, confidence, metadata_json
          )
          values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s::jsonb)
          returning id, project_id, user_id, chat_session_id, label, intent_family, memory_scope,
            topic_tags, rolling_summary, related_paths_json, related_modules_json, last_prompt,
            last_changed_paths_json, status, confidence, metadata_json, created_at, updated_at
          """,
          (
            topic_id,
            project_id,
            user.id,
            chat_session_id,
            label.strip()[:160] or "Chat task",
            intent_family.strip()[:120] or "general",
            memory_scope.strip()[:80] or "topic",
            topic_tags.strip()[:500],
            rolling_summary.strip()[:6000],
            json_dumps_safe([str(path)[:240] for path in (related_paths or [])[:40]], context="memory.topic.paths"),
            json_dumps_safe([str(module)[:160] for module in (related_modules or [])[:24]], context="memory.topic.modules"),
            last_prompt.strip()[:1200],
            json_dumps_safe([str(path)[:240] for path in (last_changed_paths or [])[:40]], context="memory.topic.changed_paths"),
            _bounded_confidence(confidence),
            json_dumps_safe(metadata or {}, context="memory.topic.metadata"),
          ),
        )
        row = serialize_row(cursor.fetchone())
    self.add_event(
      project_id,
      user.id,
      "memory.chat_topic.created",
      {"chat_topic_id": topic_id, "chat_session_id": chat_session_id, "intent_family": row.get("intent_family")},
    )
    return row

  def list_memory_chat_topics(
    self,
    user: UserContext,
    *,
    project_id: str,
    chat_session_id: str,
    limit: int = 12,
    status: str | None = "active",
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    safe_limit = max(1, min(int(limit or 12), 50))
    filters = ["project_id = %s", "user_id = %s", "chat_session_id = %s"]
    params: list[Any] = [project_id, user.id, chat_session_id]
    if status:
      filters.append("status = %s")
      params.append(status.strip().lower())
    params.append(safe_limit)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, project_id, user_id, chat_session_id, label, intent_family, memory_scope,
            topic_tags, rolling_summary, related_paths_json, related_modules_json, last_prompt,
            last_changed_paths_json, status, confidence, metadata_json, created_at, updated_at
          from memory_chat_topics
          where {' and '.join(filters)}
          order by updated_at desc
          limit %s
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def get_memory_chat_topic(
    self,
    user: UserContext,
    *,
    chat_topic_id: str,
  ) -> dict[str, Any] | None:
    topic_id = str(chat_topic_id or "").strip()
    if not topic_id:
      return None
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, user_id, chat_session_id, label, intent_family, memory_scope,
            topic_tags, rolling_summary, related_paths_json, related_modules_json, last_prompt,
            last_changed_paths_json, status, confidence, metadata_json, created_at, updated_at
          from memory_chat_topics
          where id = %s and user_id = %s
          limit 1
          """,
          (topic_id, user.id),
        )
        row = cursor.fetchone()
    return serialize_row(row) if row else None

  def update_memory_chat_topic(
    self,
    user: UserContext,
    *,
    chat_topic_id: str,
    label: str | None = None,
    intent_family: str | None = None,
    memory_scope: str | None = None,
    topic_tags: str | None = None,
    rolling_summary: str | None = None,
    related_paths: list[str] | None = None,
    related_modules: list[str] | None = None,
    last_prompt: str | None = None,
    last_changed_paths: list[str] | None = None,
    status: str | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any] | None:
    topic = self.get_memory_chat_topic(user, chat_topic_id=chat_topic_id)
    if not topic:
      return None
    project = require_project(self, str(topic.get("project_id") or ""), user)
    ensure_project_write(user, project)

    next_metadata = dict(topic.get("metadata_json") if isinstance(topic.get("metadata_json"), dict) else {})
    if metadata:
      next_metadata.update(metadata)
    next_paths = related_paths if related_paths is not None else (topic.get("related_paths_json") or [])
    next_modules = related_modules if related_modules is not None else (topic.get("related_modules_json") or [])
    next_changed_paths = last_changed_paths if last_changed_paths is not None else (topic.get("last_changed_paths_json") or [])
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update memory_chat_topics
          set label = %s,
              intent_family = %s,
              memory_scope = %s,
              topic_tags = %s,
              rolling_summary = %s,
              related_paths_json = %s::jsonb,
              related_modules_json = %s::jsonb,
              last_prompt = %s,
              last_changed_paths_json = %s::jsonb,
              status = %s,
              confidence = %s,
              metadata_json = %s::jsonb,
              updated_at = now()
          where id = %s and user_id = %s
          returning id, project_id, user_id, chat_session_id, label, intent_family, memory_scope,
            topic_tags, rolling_summary, related_paths_json, related_modules_json, last_prompt,
            last_changed_paths_json, status, confidence, metadata_json, created_at, updated_at
          """,
          (
            (label if label is not None else str(topic.get("label") or "")).strip()[:160] or "Chat task",
            (intent_family if intent_family is not None else str(topic.get("intent_family") or "")).strip()[:120] or "general",
            (memory_scope if memory_scope is not None else str(topic.get("memory_scope") or "")).strip()[:80] or "topic",
            (topic_tags if topic_tags is not None else str(topic.get("topic_tags") or "")).strip()[:500],
            (rolling_summary if rolling_summary is not None else str(topic.get("rolling_summary") or "")).strip()[:6000],
            json_dumps_safe([str(path)[:240] for path in list(next_paths or [])[:40]], context="memory.topic.paths"),
            json_dumps_safe([str(module)[:160] for module in list(next_modules or [])[:24]], context="memory.topic.modules"),
            (last_prompt if last_prompt is not None else str(topic.get("last_prompt") or "")).strip()[:1200],
            json_dumps_safe([str(path)[:240] for path in list(next_changed_paths or [])[:40]], context="memory.topic.changed_paths"),
            (status if status is not None else str(topic.get("status") or "active")).strip().lower() or "active",
            _bounded_confidence(confidence, default=float(topic.get("confidence") or 0.6)),
            json_dumps_safe(next_metadata, context="memory.topic.metadata"),
            chat_topic_id,
            user.id,
          ),
        )
        row = cursor.fetchone()
        return serialize_row(row) if row else None
