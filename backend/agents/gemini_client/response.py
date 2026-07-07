from __future__ import annotations

from typing import Any

from .errors import GeminiClientError


def extract_text(response: dict[str, Any]) -> str:
  try:
    parts = response["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts).strip()
  except (KeyError, IndexError, TypeError) as exc:
    raise GeminiClientError(f"Unexpected Gemini response shape: {response}") from exc


def extract_finish_reason(response: dict[str, Any]) -> str:
  try:
    reason = response["candidates"][0].get("finishReason")
  except (KeyError, IndexError, TypeError):
    return ""
  return str(reason or "").strip().upper()
