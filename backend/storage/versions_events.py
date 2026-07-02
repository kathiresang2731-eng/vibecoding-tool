from __future__ import annotations

from typing import Any

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project, require_write
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext

class VersionEventStoreMixin:
  def create_version(
    self,
    project_id: str,
    user: UserContext,
    *,
    version_id: str | None = None,
    status: str,
    preview_url: str | None,
    build_log: str,
    files: list[dict[str, str]],
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    version_id = version_id or new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into project_versions (id, project_id, status, preview_url, build_log)
          values (%s, %s, %s, %s, %s)
          returning id, project_id, status, preview_url, build_log, created_at
          """,
          (version_id, project_id, status, preview_url, build_log),
        )
        version = cursor.fetchone()
        for file_item in files:
          cursor.execute(
            "insert into project_version_files (version_id, path, content) values (%s, %s, %s)",
            (version_id, file_item["path"], file_item["content"]),
          )
    self.add_event(project_id, user.id, "preview.built", {"version_id": version_id, "status": status})
    return serialize_row(version)

  def get_version(self, project_id: str, version_id: str, user: UserContext) -> dict[str, Any] | None:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, status, preview_url, build_log, created_at
          from project_versions
          where project_id = %s and id = %s
          """,
          (project_id, version_id),
        )
        row = cursor.fetchone()
    return serialize_row(row) if row else None

  def add_event(self, project_id: str | None, user_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "insert into events (id, project_id, user_id, type, payload_json) values (%s, %s, %s, %s, %s::jsonb)",
          (new_id(), project_id, user_id, event_type, json_dumps_safe(payload, context="event.payload")),
        )

  def list_events(self, user: UserContext, *, project_id: str | None = None) -> list[dict[str, Any]]:
    if project_id:
      project = require_project(self, project_id, user)
      ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if project_id:
          cursor.execute(
            "select id, project_id, type, payload_json, created_at from events where project_id = %s order by created_at desc limit 100",
            (project_id,),
          )
        elif user.role == "admin":
          cursor.execute(
            "select id, project_id, type, payload_json, created_at from events order by created_at desc limit 100"
          )
        else:
          cursor.execute(
            """
            select e.id, e.project_id, e.type, e.payload_json, e.created_at
            from events e
            join projects p on p.id = e.project_id
            where p.owner_user_id = %s
            order by e.created_at desc
            limit 100
            """,
            (user.id,),
          )
        return [serialize_row(row) for row in cursor.fetchall()]
