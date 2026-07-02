from __future__ import annotations

import json
from typing import Any
from .roles import READ_ROLES, WRITE_ROLES

from .errors import StorageError
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project, require_write
from .serialization import serialize_row
from .user import UserContext

class ProjectFileStoreMixin:
  def ensure_user(self, email: str, *, role: str = "admin") -> UserContext:
    normalized_email = email.strip().lower()
    if role not in READ_ROLES:
      role = "viewer"
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("select id, email, role, display_name from users where email = %s", (normalized_email,))
        row = cursor.fetchone()
        if row:
          return UserContext(
            id=row["id"],
            email=row["email"],
            role=row["role"],
            display_name=row.get("display_name") or "",
          )
        user_id = new_id()
        cursor.execute(
          "insert into users (id, email, role, display_name) values (%s, %s, %s, %s)",
          (user_id, normalized_email, role, ""),
        )
        return UserContext(id=user_id, email=normalized_email, role=role, display_name="")

  def list_projects(self, user: UserContext) -> list[dict[str, Any]]:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if user.role == "admin":
          cursor.execute(
            "select id, name, description, owner_user_id, local_path, created_at, updated_at from projects order by updated_at desc"
          )
        else:
          cursor.execute(
            """
            select id, name, description, owner_user_id, local_path, created_at, updated_at
            from projects
            where owner_user_id = %s
            order by updated_at desc
            """,
            (user.id,),
          )
        return [serialize_row(row) for row in cursor.fetchall()]

  def create_project(self, user: UserContext, *, name: str, description: str = "") -> dict[str, Any]:
    require_write(user)
    project_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into projects (id, owner_user_id, name, description)
          values (%s, %s, %s, %s)
          """,
          (project_id, user.id, name.strip() or "Untitled project", description.strip()),
        )
    self.add_event(project_id, user.id, "project.created", {"name": name})
    project = self.get_project(project_id, user)
    if not project:
      raise StorageError("Project was created but could not be loaded.")
    return project

  def update_project(self, project_id: str, user: UserContext, *, name: str | None = None) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    next_name = (name or "").strip()
    if not next_name:
      raise StorageError("Project name cannot be empty.")
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update projects
          set name = %s, updated_at = now()
          where id = %s
          returning id, name, description, owner_user_id, local_path, created_at, updated_at
          """,
          (next_name, project_id),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "project.renamed", {"name": next_name})
    return serialize_row(row)

  def delete_project(self, project_id: str, user: UserContext) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("delete from projects where id = %s", (project_id,))
    return project

  def get_project(self, project_id: str, user: UserContext) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select id, name, description, owner_user_id, local_path, created_at, updated_at from projects where id = %s",
          (project_id,),
        )
        row = cursor.fetchone()
    if not row:
      return None
    project = serialize_row(row)
    ensure_project_read(user, project)
    return project

  def list_files(self, project_id: str, user: UserContext) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "select path, content, updated_at from project_files where project_id = %s order by path",
          (project_id,),
        )
        return [serialize_row(row) for row in cursor.fetchall()]

  def upsert_file(
    self,
    project_id: str,
    user: UserContext,
    *,
    path: str,
    content: str,
    emit_event: bool = True,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into project_files (project_id, path, content, updated_at)
          values (%s, %s, %s, now())
          on conflict (project_id, path)
          do update set content = excluded.content, updated_at = now()
          returning path, content, updated_at
          """,
          (project_id, path, content),
        )
        row = cursor.fetchone()
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
    if emit_event:
      self.add_event(project_id, user.id, "file.saved", {"path": path})
    return serialize_row(row)

  def set_project_local_path(self, project_id: str, user: UserContext, local_path: str) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update projects
          set local_path = %s, updated_at = now()
          where id = %s
          returning id, name, description, owner_user_id, local_path, created_at, updated_at
          """,
          (local_path, project_id),
        )
        row = cursor.fetchone()
    self.add_event(project_id, user.id, "local.path.linked", {"path": local_path})
    return serialize_row(row)

  def replace_project_files(
    self,
    project_id: str,
    user: UserContext,
    files: list[dict[str, str]],
    *,
    event_type: str = "files.synced",
    event_payload: dict[str, Any] | None = None,
  ) -> None:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute("delete from project_files where project_id = %s", (project_id,))
        for file_item in files:
          cursor.execute(
            """
            insert into project_files (project_id, path, content, updated_at)
            values (%s, %s, %s, now())
            """,
            (project_id, file_item["path"], file_item["content"]),
          )
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
    payload = {"count": len(files)}
    if event_payload:
      payload.update(event_payload)
    self.add_event(project_id, user.id, event_type, payload)

  def upsert_project_files(
    self,
    project_id: str,
    user: UserContext,
    files: list[dict[str, str]],
    *,
    event_type: str = "files.upserted",
    event_payload: dict[str, Any] | None = None,
  ) -> int:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    for file_item in files:
      self.upsert_file(
        project_id,
        user,
        path=file_item["path"],
        content=file_item["content"],
        emit_event=False,
      )
    payload = {"count": len(files)}
    if event_payload:
      payload.update(event_payload)
    self.add_event(project_id, user.id, event_type, payload)
    return len(files)

  def apply_generated_files(self, project_id: str, user: UserContext, files: list[dict[str, str]]) -> None:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        for file_item in files:
          cursor.execute(
            """
            insert into project_files (project_id, path, content, updated_at)
            values (%s, %s, %s, now())
            on conflict (project_id, path)
            do update set content = excluded.content, updated_at = now()
            """,
            (project_id, file_item["path"], file_item["code"]),
          )
        cursor.execute("update projects set updated_at = now() where id = %s", (project_id,))
    self.add_event(project_id, user.id, "files.generated", {"count": len(files)})

