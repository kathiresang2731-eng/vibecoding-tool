from __future__ import annotations

from typing import Any

from .errors import GeminiToolCallingError


def messages_to_gemini_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  contents: list[dict[str, Any]] = []
  for message in messages:
    if not isinstance(message, dict):
      continue
    role = "model" if message.get("role") in {"assistant", "model"} else "user"
    parts: list[dict[str, Any]] = []
    inline_parts = message.get("inline_parts")
    if isinstance(inline_parts, list):
      for part in inline_parts:
        if isinstance(part, dict) and part:
          parts.append(part)
    attachments = message.get("attachments")
    if isinstance(attachments, list):
      try:
        from ..prompting.attachments import gemini_inline_image_parts, normalize_prompt_attachments
      except ImportError:
        from agents.prompting.attachments import gemini_inline_image_parts, normalize_prompt_attachments
      parts.extend(gemini_inline_image_parts(normalize_prompt_attachments(attachments)))
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
      text = message.get("text")
    if isinstance(text, str) and text.strip():
      parts.append({"text": text})
    if parts:
      contents.append({"role": role, "parts": parts})
  if not contents:
    raise GeminiToolCallingError("Messages did not contain any text or attachment content.")
  return contents
