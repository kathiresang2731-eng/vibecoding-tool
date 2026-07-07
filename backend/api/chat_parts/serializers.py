from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_metadata(metadata: Any) -> dict[str, Any]:
  if isinstance(metadata, dict):
    return metadata
  return {}


def parse_timestamp(value: Any) -> datetime | None:
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


def format_relative_time(value: Any) -> str:
  parsed = parse_timestamp(value)
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


def last_user_prompt(messages: list[dict[str, Any]]) -> str:
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
  metadata = normalize_metadata(row.get("metadata_json"))
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

