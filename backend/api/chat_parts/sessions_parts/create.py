from __future__ import annotations

from typing import Any

from ..serializers import serialize_chat_session_for_api


def create_project_chat_session_payload(
  project_id: str,
  store: Any,
  user: Any,
  *,
  title: str = "",
  settings: Any | None = None,
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise ValueError("Project not found.")
  active_sessions = (
    store.list_chat_sessions(project_id, user, limit=5, status="active")
    if hasattr(store, "list_chat_sessions")
    else []
  )
  if active_sessions and settings is not None:
    try:
      from ...agents.memory.session_extraction import extract_closed_session_memories
    except ImportError:
      from agents.memory.session_extraction import extract_closed_session_memories
    for session in active_sessions:
      session_id = str(session.get("id") or "")
      if session_id:
        extract_closed_session_memories(
          store,
          user,
          project_id=project_id,
          chat_session_id=session_id,
          settings=settings,
        )
  store.close_active_chat_sessions(project_id, user)
  session = store.create_chat_session(project_id, user, title=title)
  return {
    "project_id": project_id,
    "user_id": user.id,
    "session": serialize_chat_session_for_api(session),
  }

