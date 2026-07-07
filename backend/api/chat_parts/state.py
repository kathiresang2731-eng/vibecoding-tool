from __future__ import annotations

from typing import Any

from .serializers import format_relative_time, last_user_prompt, normalize_metadata


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
  relative_time = format_relative_time(last_activity_at)
  if episodic_memories:
    latest = episodic_memories[0]
    latest_meta = normalize_metadata(latest.get("metadata_json") or latest.get("metadata"))
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
    for message in reversed(messages):
      message_meta = normalize_metadata(message.get("metadata"))
      message_intent = str(message_meta.get("intent") or "").strip()
      if not message_intent:
        continue
      last_intent = message_intent
      last_outcome = str(message_meta.get("outcome") or "").strip()
      intent_label = last_intent.replace("_", " ")
      outcome_label = last_outcome or "completed"
      resume_hint = f"Last run: {intent_label} ({outcome_label})."
      break
    last_prompt = last_user_prompt(messages)
    if not resume_hint and last_prompt:
      resume_hint = f'Continuing your thread — last request: "{last_prompt}".'
    elif not resume_hint:
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
