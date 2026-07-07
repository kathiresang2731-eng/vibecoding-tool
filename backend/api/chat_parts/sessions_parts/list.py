from __future__ import annotations

from typing import Any

try:
  from ...agents.memory.episodic import list_episodic_memories, serialize_episodic_memory_for_api
except ImportError:
  from agents.memory.episodic import list_episodic_memories, serialize_episodic_memory_for_api

from ..serializers import apply_confirmation_overrides, last_user_prompt, serialize_chat_message_for_api, serialize_chat_session_for_api
from ..state import build_conversation_state
from .ensure import ensure_project_chat_session


def list_project_chat_sessions_payload(
  project_id: str,
  store: Any,
  user: Any,
  *,
  limit: int = 20,
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise ValueError("Project not found.")
  sessions = store.list_chat_sessions(project_id, user, limit=limit)
  return {
    "project_id": project_id,
    "user_id": user.id,
    "sessions": [serialize_chat_session_for_api(item) for item in sessions],
    "count": len(sessions),
  }


def list_project_chat_payload(
  project_id: str,
  store: Any,
  user: Any,
  *,
  limit: int = 200,
  chat_session_id: str | None = None,
) -> dict[str, Any]:
  project = store.get_project(project_id, user)
  if not project:
    raise ValueError("Project not found.")

  session = ensure_project_chat_session(project_id, store, user, chat_session_id=chat_session_id)
  resolved_session_id = session["id"]
  rows = store.list_project_chat_messages(project_id, user, limit=limit, chat_session_id=resolved_session_id)
  messages = apply_confirmation_overrides([serialize_chat_message_for_api(row) for row in rows])
  episodic_memories = list_episodic_memories(
    store,
    user,
    project_id=project_id,
    chat_session_id=resolved_session_id,
    prompt=last_user_prompt(messages),
  )
  conversation = build_conversation_state(messages, episodic_memories, chat_session=session)
  session_memory_state = None
  if hasattr(store, "get_memory_chat_session_state"):
    session_memory_state = store.get_memory_chat_session_state(
      user,
      project_id=project_id,
      chat_session_id=resolved_session_id,
    )
  structured_episodes = []
  if hasattr(store, "list_memory_episodes"):
    structured_episodes = store.list_memory_episodes(
      user,
      project_id=project_id,
      chat_session_id=resolved_session_id,
      scope="personal",
      limit=6,
    )
  return {
    "project_id": project_id,
    "user_id": user.id,
    "chat_session": session,
    "messages": messages,
    "conversation": conversation,
    "episodic_memories": [serialize_episodic_memory_for_api(item) for item in episodic_memories if isinstance(item, dict)],
    "session_memory_state": session_memory_state,
    "structured_episodes": structured_episodes,
  }
