from __future__ import annotations

from typing import Any

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project, require_write
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext

class MemoryStoreMixin:
  def upsert_memory_item(
    self,
    user: UserContext,
    *,
    namespace: str,
    key: str,
    kind: str,
    content: str,
    project_id: str | None = None,
    metadata: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_write(user, project)
    else:
      require_write(user)

    memory_id = new_id()
    normalized_namespace = namespace.strip() or "project"
    normalized_key = key.strip()
    if not normalized_key:
      raise StorageError("Memory key cannot be empty.")

    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update memory_items
          set kind = %s,
            content = %s,
            metadata_json = %s::jsonb,
            updated_at = now()
          where project_id is not distinct from %s
            and user_id = %s
            and namespace = %s
            and key = %s
          returning id, project_id, user_id, namespace, key, kind, content, metadata_json, created_at, updated_at
          """,
          (
            kind.strip() or "summary",
            content,
            json_dumps_safe(metadata or {}, context="memory.metadata"),
            project_id,
            user.id,
            normalized_namespace,
            normalized_key,
          ),
        )
        row = cursor.fetchone()
        if not row:
          cursor.execute(
            """
            insert into memory_items (id, project_id, user_id, namespace, key, kind, content, metadata_json)
            values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            returning id, project_id, user_id, namespace, key, kind, content, metadata_json, created_at, updated_at
            """,
            (
              memory_id,
              project_id,
              user.id,
              normalized_namespace,
              normalized_key,
              kind.strip() or "summary",
              content,
              json_dumps_safe(metadata or {}, context="memory.metadata"),
            ),
          )
          row = cursor.fetchone()
    if project_id:
      self.add_event(project_id, user.id, "memory.upserted", {"namespace": normalized_namespace, "key": normalized_key})
    return serialize_row(row)

  def list_memory_items(
    self,
    user: UserContext,
    *,
    project_id: str | None = None,
    namespace: str | None = None,
    kind: str | None = None,
    limit: int = 12,
  ) -> list[dict[str, Any]]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_read(user, project)
    else:
      require_write(user)

    safe_limit = max(1, min(limit, 50))
    filters = ["user_id = %s"]
    params: list[Any] = [user.id]
    if project_id:
      filters.append("project_id = %s")
      params.append(project_id)
    if namespace:
      filters.append("namespace = %s")
      params.append(namespace.strip())
    if kind:
      filters.append("kind = %s")
      params.append(kind.strip())
    params.append(safe_limit)

    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, project_id, user_id, namespace, key, kind, content, metadata_json, created_at, updated_at
          from memory_items
          where {' and '.join(filters)}
          order by updated_at desc
          limit %s
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def prune_memory_items(
    self,
    user: UserContext,
    *,
    project_id: str,
    namespace: str,
    kind: str,
    keep: int,
  ) -> int:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    safe_keep = max(1, min(int(keep or 1), 50))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          delete from memory_items
          where id in (
            select id
            from memory_items
            where project_id = %s
              and user_id = %s
              and namespace = %s
              and kind = %s
            order by updated_at desc
            offset %s
          )
          """,
          (project_id, user.id, namespace.strip(), kind.strip(), safe_keep),
        )
        return cursor.rowcount

  def list_dynamic_agent_definitions(
    self,
    user: UserContext,
    *,
    include_disabled: bool = False,
  ) -> list[dict[str, Any]]:
    require_write(user)
    filters = ["owner_user_id = %s"]
    params: list[Any] = [user.id]
    if not include_disabled:
      filters.append("lifecycle != 'disabled'")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          f"""
          select id, owner_user_id, agent_key, version, lifecycle, definition_json,
            metrics_json, created_at, updated_at
          from dynamic_agent_definitions
          where {' and '.join(filters)}
          order by updated_at desc
          """,
          tuple(params),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def upsert_dynamic_agent_definition(
    self,
    user: UserContext,
    *,
    agent_key: str,
    lifecycle: str,
    definition: dict[str, Any],
    metrics: dict[str, Any],
  ) -> dict[str, Any]:
    require_write(user)
    normalized_key = agent_key.strip()
    if not normalized_key:
      raise StorageError("Dynamic agent key cannot be empty.")
    agent_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update dynamic_agent_definitions
          set version = version + 1,
            lifecycle = %s,
            definition_json = %s::jsonb,
            metrics_json = %s::jsonb,
            updated_at = now()
          where owner_user_id = %s and agent_key = %s
          returning id, owner_user_id, agent_key, version, lifecycle, definition_json,
            metrics_json, created_at, updated_at
          """,
          (
            lifecycle.strip() or "experimental",
            json_dumps_safe(definition, context="dynamic_agent.definition"),
            json_dumps_safe(metrics, context="dynamic_agent.metrics"),
            user.id,
            normalized_key,
          ),
        )
        row = cursor.fetchone()
        if not row:
          cursor.execute(
            """
            insert into dynamic_agent_definitions (
              id, owner_user_id, agent_key, lifecycle, definition_json, metrics_json
            )
            values (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            returning id, owner_user_id, agent_key, version, lifecycle, definition_json,
              metrics_json, created_at, updated_at
            """,
            (
              agent_id,
              user.id,
              normalized_key,
              lifecycle.strip() or "experimental",
              json_dumps_safe(definition, context="dynamic_agent.definition"),
              json_dumps_safe(metrics, context="dynamic_agent.metrics"),
            ),
          )
          row = cursor.fetchone()
    return serialize_row(row)
