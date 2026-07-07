from __future__ import annotations

import json
from typing import Any

from .errors import OpenAIToolCallingError
from .models import FunctionCall
from .values import string_value


def extract_function_calls(response: dict[str, Any]) -> list[FunctionCall]:
  output_items = response.get("output")
  if not isinstance(output_items, list):
    return []

  calls: list[FunctionCall] = []
  for item in output_items:
    if not isinstance(item, dict) or item.get("type") != "function_call":
      continue
    call_id = string_value(item.get("call_id") or item.get("id"))
    name = string_value(item.get("name"))
    raw_arguments = item.get("arguments")
    if not call_id or not name:
      raise OpenAIToolCallingError("OpenAI function call missing call_id or name.")
    calls.append(
      FunctionCall(
        call_id=call_id,
        name=name,
        arguments=parse_tool_arguments(raw_arguments),
        raw=item,
      )
    )
  return calls


def extract_output_text(response: dict[str, Any]) -> str:
  output_text = response.get("output_text")
  if isinstance(output_text, str) and output_text.strip():
    return output_text.strip()

  chunks: list[str] = []
  output_items = response.get("output")
  if not isinstance(output_items, list):
    return ""
  for item in output_items:
    if not isinstance(item, dict) or item.get("type") != "message":
      continue
    content_items = item.get("content")
    if not isinstance(content_items, list):
      continue
    for content_item in content_items:
      if not isinstance(content_item, dict):
        continue
      text = content_item.get("text")
      if isinstance(text, str):
        chunks.append(text)
  return "".join(chunks).strip()


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
  if raw_arguments is None or raw_arguments == "":
    return {}
  if isinstance(raw_arguments, dict):
    return raw_arguments
  if not isinstance(raw_arguments, str):
    raise OpenAIToolCallingError("Function call arguments must be a JSON object or string.")
  try:
    parsed = json.loads(raw_arguments)
  except json.JSONDecodeError as exc:
    raise OpenAIToolCallingError(f"Function call arguments are invalid JSON: {raw_arguments[:400]}") from exc
  if not isinstance(parsed, dict):
    raise OpenAIToolCallingError("Function call arguments must decode to a JSON object.")
  return parsed
