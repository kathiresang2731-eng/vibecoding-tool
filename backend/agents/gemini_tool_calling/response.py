from __future__ import annotations

import json
from typing import Any

from ..gemini_client import extract_text
from .errors import GeminiToolCallingError
from .models import GeminiFunctionCall
from .values import string_value


def extract_function_calls(response: dict[str, Any]) -> list[GeminiFunctionCall]:
  calls: list[GeminiFunctionCall] = []
  content = first_candidate_content(response)
  parts = content.get("parts") if isinstance(content, dict) else None
  if not isinstance(parts, list):
    return calls
  for part in parts:
    if not isinstance(part, dict):
      continue
    raw_call = part.get("functionCall") or part.get("function_call")
    if not isinstance(raw_call, dict):
      continue
    name = string_value(raw_call.get("name"))
    call_id = string_value(raw_call.get("id")) or string_value(raw_call.get("call_id")) or f"gemini-call-{len(calls) + 1}"
    if not name:
      raise GeminiToolCallingError("Gemini function call missing name.")
    args = raw_call.get("args") or raw_call.get("arguments") or {}
    if isinstance(args, str):
      try:
        args = json.loads(args)
      except json.JSONDecodeError as exc:
        raise GeminiToolCallingError(f"Gemini function call arguments are invalid JSON: {args[:400]}") from exc
    if not isinstance(args, dict):
      raise GeminiToolCallingError("Gemini function call arguments must be a JSON object.")
    calls.append(GeminiFunctionCall(call_id=call_id, name=name, arguments=args, raw=raw_call))
  return calls


def first_candidate_content(response: dict[str, Any]) -> dict[str, Any]:
  candidates = response.get("candidates")
  if not isinstance(candidates, list) or not candidates:
    return {}
  candidate = candidates[0]
  if not isinstance(candidate, dict):
    return {}
  content = candidate.get("content")
  return content if isinstance(content, dict) else {}


def extract_text_or_empty(response: dict[str, Any]) -> str:
  try:
    return extract_text(response)
  except Exception:
    return ""
