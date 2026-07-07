from __future__ import annotations

from typing import Any

from ..serializers import serialize_chat_session_for_api


def ensure_project_chat_session(
  project_id: str,
  store: Any,
  user: Any,
  *,
  chat_session_id: str | None = None,
) -> dict[str, Any]:
  if chat_session_id:
    session = store.get_chat_session(chat_session_id, user)
    if not session or session.get("project_id") != project_id:
      raise ValueError("Chat session not found for this project.")
    return serialize_chat_session_for_api(session)
  session = store.ensure_active_chat_session(project_id, user)
  store._attach_legacy_messages_to_session(project_id, user, session["id"])
  return serialize_chat_session_for_api(session)

