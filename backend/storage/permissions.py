from __future__ import annotations

from typing import Any

from .errors import StorageError
from .roles import READ_ROLES, WRITE_ROLES
from .user import UserContext


def require_project(store: Any, project_id: str, user: UserContext) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise StorageError("Project not found.")
  return project


def require_write(user: UserContext) -> None:
  if user.role not in WRITE_ROLES:
    raise StorageError("User does not have write access.")


def ensure_project_read(user: UserContext, project: dict[str, Any]) -> None:
  if user.role == "admin":
    return
  if user.role in READ_ROLES and project.get("owner_user_id") == user.id:
    return
  raise StorageError("User does not have access to this project.")


def ensure_project_write(user: UserContext, project: dict[str, Any]) -> None:
  if user.role == "admin":
    return
  if user.role in WRITE_ROLES and project.get("owner_user_id") == user.id:
    return
  raise StorageError("User does not have write access to this project.")


def require_memory_scope(
  store: Any,
  user: UserContext,
  *,
  project_id: str,
  chat_session_id: str,
  chat_topic_id: str | None = None,
  generation_run_id: str | None = None,
  write: bool = False,
) -> dict[str, Any]:
  """Validate that every supplied memory identifier belongs to one project/user scope."""
  project = require_project(store, project_id, user)
  if write:
    ensure_project_write(user, project)
  else:
    ensure_project_read(user, project)

  session_id = str(chat_session_id or "").strip()
  if not session_id:
    raise StorageError("Chat session id is required for scoped memory.")
  with store.connect() as conn:
    with conn.cursor() as cursor:
      cursor.execute(
        """
        select id, project_id, user_id
        from project_chat_sessions
        where id = %s and project_id = %s and user_id = %s
        limit 1
        """,
        (session_id, project_id, user.id),
      )
      session = cursor.fetchone()
      if not session:
        raise StorageError("Chat session does not belong to this project and user.")

      topic_id = str(chat_topic_id or "").strip()
      if topic_id:
        cursor.execute(
          """
          select id
          from memory_chat_topics
          where id = %s and project_id = %s and user_id = %s and chat_session_id = %s
          limit 1
          """,
          (topic_id, project_id, user.id, session_id),
        )
        if not cursor.fetchone():
          raise StorageError("Chat topic does not belong to this project session.")

      run_id = str(generation_run_id or "").strip()
      if run_id:
        cursor.execute(
          """
          select id
          from generation_runs
          where id = %s and project_id = %s and user_id = %s
          limit 1
          """,
          (run_id, project_id, user.id),
        )
        if not cursor.fetchone():
          raise StorageError("Generation run does not belong to this project and user.")
  return {
    "project": project,
    "chat_session_id": session_id,
    "chat_topic_id": str(chat_topic_id or "").strip() or None,
    "generation_run_id": str(generation_run_id or "").strip() or None,
  }
