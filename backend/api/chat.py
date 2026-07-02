"""Project chat history API — Postgres-backed user/model turns + continuity state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
  from ..agents.memory.episodic import list_episodic_memories, serialize_episodic_memory_for_api
except ImportError:
  from agents.memory.episodic import list_episodic_memories, serialize_episodic_memory_for_api


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
  if isinstance(metadata, dict):
    return metadata
  return {}


def _parse_timestamp(value: Any) -> datetime | None:
  text = str(value or "").strip()
  if not text:
    return None
  try:
    if text.endswith("Z"):
      text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
      parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
  except ValueError:
    return None


def _format_relative_time(value: Any) -> str:
  parsed = _parse_timestamp(value)
  if not parsed:
    return ""
  delta = datetime.now(timezone.utc) - parsed
  seconds = max(int(delta.total_seconds()), 0)
  if seconds < 60:
    return "just now"
  minutes = seconds // 60
  if minutes < 60:
    return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
  hours = minutes // 60
  if hours < 24:
    return f"{hours} hour{'s' if hours != 1 else ''} ago"
  days = hours // 24
  if days < 14:
    return f"{days} day{'s' if days != 1 else ''} ago"
  weeks = days // 7
  if weeks < 8:
    return f"{weeks} week{'s' if weeks != 1 else ''} ago"
  months = days // 30
  if months < 24:
    return f"{months} month{'s' if months != 1 else ''} ago"
  years = days // 365
  return f"{years} year{'s' if years != 1 else ''} ago"


def _last_user_prompt(messages: list[dict[str, Any]]) -> str:
  for message in reversed(messages):
    if message.get("role") == "user":
      content = str(message.get("content") or "").strip()
      if content:
        return content[:160]
  return ""


def serialize_chat_session_for_api(row: dict[str, Any]) -> dict[str, Any]:
  return {
    "id": row.get("id"),
    "project_id": row.get("project_id"),
    "user_id": row.get("user_id"),
    "title": row.get("title") or "",
    "status": row.get("status") or "active",
    "created_at": row.get("created_at"),
    "updated_at": row.get("updated_at"),
  }


def serialize_chat_message_for_api(row: dict[str, Any]) -> dict[str, Any]:
  metadata = _normalize_metadata(row.get("metadata_json"))
  stored_role = str(row.get("role") or "").strip().lower()
  api_role = "assistant" if stored_role == "model" else "user"
  display_content = str(metadata.get("display_content") or row.get("content") or "").strip()
  confirmation = metadata.get("confirmation")
  attachments = metadata.get("attachments")
  if not isinstance(attachments, list):
    attachments = []
  return {
    "id": row.get("id"),
    "user_id": row.get("user_id"),
    "chat_session_id": row.get("chat_session_id"),
    "role": api_role,
    "content": display_content,
    "metadata": metadata,
    "attachments": attachments,
    "confirmation": confirmation if isinstance(confirmation, dict) else None,
    "created_at": row.get("created_at"),
  }


def apply_confirmation_overrides(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  cancelled = any(
    "cancel the pending execution brief" in str(message.get("content") or "").lower()
    for message in messages
    if message.get("role") == "user"
  )
  if not cancelled:
    return messages
  return [
    {
      **message,
      "confirmation": (
        {**message["confirmation"], "status": "cancelled"}
        if message.get("role") == "assistant"
        and isinstance(message.get("confirmation"), dict)
        and message["confirmation"].get("status") == "pending"
        else message.get("confirmation")
      ),
    }
    for message in messages
  ]


def build_conversation_state(
  messages: list[dict[str, Any]],
  episodic_memories: list[dict[str, Any]],
  *,
  chat_session: dict[str, Any] | None = None,
) -> dict[str, Any]:
  has_pending_confirmation = any(
    isinstance(message.get("confirmation"), dict) and message["confirmation"].get("status") == "pending"
    for message in messages
  )
  has_pending_patch_approval = any(
    isinstance(message.get("patch_approval"), dict) and message["patch_approval"].get("status") == "pending"
    for message in messages
  )
  last_intent = ""
  last_outcome = ""
  resume_hint = ""
  last_activity_at = chat_session.get("updated_at") if chat_session else ""
  if messages:
    last_activity_at = messages[-1].get("created_at") or last_activity_at
  relative_time = _format_relative_time(last_activity_at)
  if episodic_memories:
    latest = episodic_memories[0]
    latest_meta = _normalize_metadata(latest.get("metadata_json") or latest.get("metadata"))
    last_intent = str(latest_meta.get("intent") or "").strip()
    last_outcome = str(latest_meta.get("outcome") or "").strip()
    changed_paths = latest_meta.get("changed_paths")
    path_hint = ""
    if isinstance(changed_paths, list) and changed_paths:
      preview_paths = ", ".join(str(path) for path in changed_paths[:3])
      path_hint = f" Updated files include {preview_paths}."
    if last_intent:
      intent_label = last_intent.replace("_", " ")
      outcome_label = last_outcome or "completed"
      resume_hint = f"Last run: {intent_label} ({outcome_label}).{path_hint}"
    if len(episodic_memories) > 1:
      resume_hint = f"{resume_hint} {len(episodic_memories)} recent runs are available in this chat session.".strip()
  elif messages:
    last_prompt = _last_user_prompt(messages)
    if last_prompt:
      resume_hint = f'Continuing your thread — last request: "{last_prompt}".'
    else:
      resume_hint = f"Continuing with {len(messages)} saved chat message(s) for this project."
  if relative_time and resume_hint:
    resume_hint = f"Welcome back ({relative_time}). {resume_hint}"
  elif relative_time:
    resume_hint = f"Welcome back ({relative_time}). Pick up where you left off."

  return {
    "chat_session_id": chat_session.get("id") if chat_session else "",
    "message_count": len(messages),
    "has_pending_confirmation": has_pending_confirmation,
    "has_pending_patch_approval": has_pending_patch_approval,
    "last_intent": last_intent,
    "last_outcome": last_outcome,
    "episodic_count": len(episodic_memories),
    "resume_hint": resume_hint,
    "last_activity_at": last_activity_at,
    "session_status": chat_session.get("status") if chat_session else "",
  }


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
      from ..agents.memory.session_extraction import extract_closed_session_memories
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
    prompt=_last_user_prompt(messages),
  )
  conversation = build_conversation_state(messages, episodic_memories, chat_session=session)
  session_memory_state = None
  if hasattr(store, "get_memory_chat_session_state"):
    session_memory_state = store.get_memory_chat_session_state(user, chat_session_id=resolved_session_id)
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


def record_project_chat_payload(
  project_id: str,
  store: Any,
  user: Any,
  *,
  role: str,
  content: str,
  metadata: dict[str, Any] | None = None,
  chat_session_id: str | None = None,
) -> dict[str, Any]:
  normalized_role = role.strip().lower()
  if normalized_role == "assistant":
    normalized_role = "model"
  if normalized_role not in {"user", "model"}:
    raise ValueError("Chat role must be user or assistant.")

  payload_metadata = dict(metadata or {})
  display_content = str(payload_metadata.get("display_content") or content or "").strip()
  if display_content:
    payload_metadata["display_content"] = display_content

  session = ensure_project_chat_session(project_id, store, user, chat_session_id=chat_session_id)
  row = store.record_project_chat_message(
    project_id,
    user,
    role=normalized_role,
    content=content,
    metadata=payload_metadata,
    chat_session_id=session["id"],
  )
  return {
    "user_id": user.id,
    "chat_session": session,
    "message": serialize_chat_message_for_api(row),
  }
