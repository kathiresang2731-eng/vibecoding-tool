from __future__ import annotations

from typing import Any

from ..serializers import serialize_chat_message_for_api
from .ensure import ensure_project_chat_session


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

