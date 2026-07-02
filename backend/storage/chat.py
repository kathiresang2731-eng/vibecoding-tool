from __future__ import annotations

from typing import Any

try:
  from ..debug_trace import trace_function
except ImportError:
  from debug_trace import trace_function
from .ids import new_id
from .permissions import ensure_project_read, ensure_project_write, require_project
from .serialization import json_dumps_safe, serialize_row
from .user import UserContext


class ChatHistoryStoreMixin:
  def create_chat_session(
    self,
    project_id: str,
    user: UserContext,
    *,
    title: str = "",
    status: str = "active",
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_status = status.strip().lower()
    if normalized_status not in {"active", "closed"}:
      raise ValueError("Chat session status must be active or closed.")
    session_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into project_chat_sessions (id, project_id, user_id, title, status)
          values (%s, %s, %s, %s, %s)
          returning id, project_id, user_id, title, status, created_at, updated_at
          """,
          (session_id, project_id, user.id, title.strip(), normalized_status),
        )
        row = cursor.fetchone()
    return serialize_row(row)

  def get_chat_session(self, session_id: str, user: UserContext) -> dict[str, Any] | None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, user_id, title, status, created_at, updated_at
          from project_chat_sessions
          where id = %s
          """,
          (session_id,),
        )
        row = cursor.fetchone()
    if not row:
      return None
    session = serialize_row(row)
    project = require_project(self, session["project_id"], user)
    ensure_project_read(user, project)
    if session["user_id"] != user.id and user.role != "admin":
      return None
    return session

  def list_chat_sessions(
    self,
    project_id: str,
    user: UserContext,
    *,
    limit: int = 20,
    status: str | None = None,
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    safe_limit = max(1, min(int(limit or 20), 100))
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if status:
          cursor.execute(
            """
            select id, project_id, user_id, title, status, created_at, updated_at
            from project_chat_sessions
            where project_id = %s and user_id = %s and status = %s
            order by updated_at desc
            limit %s
            """,
            (project_id, user.id, status.strip().lower(), safe_limit),
          )
        else:
          cursor.execute(
            """
            select id, project_id, user_id, title, status, created_at, updated_at
            from project_chat_sessions
            where project_id = %s and user_id = %s
            order by updated_at desc
            limit %s
            """,
            (project_id, user.id, safe_limit),
          )
        return [serialize_row(row) for row in cursor.fetchall()]

  def close_active_chat_sessions(
    self,
    project_id: str,
    user: UserContext,
    *,
    except_session_id: str | None = None,
  ) -> None:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        if except_session_id:
          cursor.execute(
            """
            update project_chat_sessions
            set status = 'closed', updated_at = now()
            where project_id = %s and user_id = %s and status = 'active' and id <> %s
            """,
            (project_id, user.id, except_session_id),
          )
        else:
          cursor.execute(
            """
            update project_chat_sessions
            set status = 'closed', updated_at = now()
            where project_id = %s and user_id = %s and status = 'active'
            """,
            (project_id, user.id),
          )

  def ensure_active_chat_session(self, project_id: str, user: UserContext) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, user_id, title, status, created_at, updated_at
          from project_chat_sessions
          where project_id = %s and user_id = %s and status = 'active'
          order by updated_at desc
          limit 1
          """,
          (project_id, user.id),
        )
        row = cursor.fetchone()
    if row:
      return serialize_row(row)
    return self.create_chat_session(project_id, user)

  def _attach_legacy_messages_to_session(self, project_id: str, user: UserContext, session_id: str) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          update project_chat_messages
          set chat_session_id = %s
          where project_id = %s and user_id = %s and chat_session_id is null
          """,
          (session_id, project_id, user.id),
        )

  def touch_chat_session(self, session_id: str) -> None:
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          "update project_chat_sessions set updated_at = now() where id = %s",
          (session_id,),
        )

  def resolve_chat_session_id(
    self,
    project_id: str,
    user: UserContext,
    chat_session_id: str | None,
  ) -> str:
    if chat_session_id:
      session = self.get_chat_session(chat_session_id, user)
      if not session or session["project_id"] != project_id:
        raise ValueError("Chat session not found for this project.")
      return session["id"]
    session = self.ensure_active_chat_session(project_id, user)
    self._attach_legacy_messages_to_session(project_id, user, session["id"])
    return session["id"]

  @trace_function(project_id=lambda _self, project_id, *_args, **_kwargs: project_id, role=lambda _self, _project_id, _user, **kwargs: kwargs.get("role"))
  def record_project_chat_message(
    self,
    project_id: str,
    user: UserContext,
    *,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    chat_session_id: str | None = None,
  ) -> dict[str, Any]:
    project = require_project(self, project_id, user)
    ensure_project_write(user, project)
    normalized_role = role.strip().lower()
    if normalized_role not in {"user", "model"}:
      raise ValueError("Project chat message role must be user or model.")
    resolved_session_id = self.resolve_chat_session_id(project_id, user, chat_session_id)
    message_id = new_id()
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          insert into project_chat_messages (id, project_id, user_id, chat_session_id, role, content, metadata_json)
          values (%s, %s, %s, %s, %s, %s, %s::jsonb)
          returning id, project_id, user_id, chat_session_id, role, content, metadata_json, created_at
          """,
          (
            message_id,
            project_id,
            user.id,
            resolved_session_id,
            normalized_role,
            content,
            json_dumps_safe(metadata or {}, context="chat.metadata"),
          ),
        )
        row = cursor.fetchone()
    self.touch_chat_session(resolved_session_id)
    return serialize_row(row)

  @trace_function(project_id=lambda _self, project_id, *_args, **_kwargs: project_id, limit=lambda _self, _project_id, _user, **kwargs: kwargs.get("limit", 80))
  def list_project_chat_messages(
    self,
    project_id: str,
    user: UserContext,
    *,
    limit: int = 80,
    chat_session_id: str | None = None,
  ) -> list[dict[str, Any]]:
    project = require_project(self, project_id, user)
    ensure_project_read(user, project)
    safe_limit = max(1, min(int(limit or 80), 200))
    resolved_session_id = self.resolve_chat_session_id(project_id, user, chat_session_id)
    with self.connect() as conn:
      with conn.cursor() as cursor:
        cursor.execute(
          """
          select id, project_id, user_id, chat_session_id, role, content, metadata_json, created_at
          from (
            select id, project_id, user_id, chat_session_id, role, content, metadata_json, created_at
            from project_chat_messages
            where project_id = %s and user_id = %s and chat_session_id = %s
            order by created_at desc
            limit %s
          ) recent
          order by created_at asc
          """,
          (project_id, user.id, resolved_session_id, safe_limit),
        )
        return [serialize_row(row) for row in cursor.fetchall()]
