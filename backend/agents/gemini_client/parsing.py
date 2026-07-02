from __future__ import annotations

import json
import re
from typing import Any

from .errors import GeminiClientError


def parse_json_text(text: str) -> dict[str, Any]:
  cleaned = strip_json_code_fence(text.strip())

  for candidate in json_parse_candidates(cleaned):
    try:
      parsed = json.loads(candidate)
      if isinstance(parsed, dict):
        return parsed
    except json.JSONDecodeError:
      pass
    try:
      parsed = json.loads(candidate, strict=False)
      if isinstance(parsed, dict):
        return parsed
    except json.JSONDecodeError:
      parsed = extract_first_json_object(candidate)
      if isinstance(parsed, dict):
        return parsed
  salvaged = salvage_json_string_fields(
    cleaned,
    fields=("intent", "next_action", "next_tool", "reason"),
    required=("intent",),
  )
  if salvaged is not None:
    return salvaged
  raise GeminiClientError(f"Gemini returned invalid JSON: {cleaned[:800]}")


def extract_first_json_object(text: str) -> dict[str, Any] | None:
  decoder = json.JSONDecoder(strict=False)
  index = text.find("{")
  if index < 0:
    return None
  try:
    parsed, _end = decoder.raw_decode(text[index:])
  except json.JSONDecodeError:
    return None
  if isinstance(parsed, dict):
    return parsed
  return None


def strip_json_code_fence(text: str) -> str:
  cleaned = text.strip()
  if not cleaned.startswith("```"):
    return cleaned
  lines = cleaned.splitlines()
  if lines and lines[0].strip().startswith("```"):
    lines = lines[1:]
  if lines and lines[-1].strip().startswith("```"):
    lines = lines[:-1]
  return "\n".join(lines).strip()


def json_parse_candidates(text: str) -> list[str]:
  candidates = [text]
  first_brace = text.find("{")
  last_brace = text.rfind("}")
  if first_brace >= 0 and last_brace > first_brace:
    candidates.append(text[first_brace : last_brace + 1])
  with_trailing_commas_removed = remove_json_trailing_commas(text)
  if with_trailing_commas_removed != text:
    candidates.append(with_trailing_commas_removed)
  if first_brace >= 0 and last_brace > first_brace:
    sliced = with_trailing_commas_removed[first_brace : last_brace + 1]
    candidates.append(sliced)
  unique_candidates: list[str] = []
  seen: set[str] = set()
  for candidate in candidates:
    if candidate and candidate not in seen:
      unique_candidates.append(candidate)
      seen.add(candidate)
  return unique_candidates


def remove_json_trailing_commas(text: str) -> str:
  output: list[str] = []
  in_string = False
  escaped = False
  index = 0
  while index < len(text):
    char = text[index]
    if in_string:
      output.append(char)
      if escaped:
        escaped = False
      elif char == "\\":
        escaped = True
      elif char == "\"":
        in_string = False
      index += 1
      continue
    if char == "\"":
      in_string = True
      output.append(char)
      index += 1
      continue
    if char == ",":
      lookahead = index + 1
      while lookahead < len(text) and text[lookahead].isspace():
        lookahead += 1
      if lookahead < len(text) and text[lookahead] in "]}":
        index += 1
        continue
    output.append(char)
    index += 1
  return "".join(output)


def salvage_json_string_fields(
  text: str,
  *,
  fields: tuple[str, ...],
  required: tuple[str, ...] = (),
) -> dict[str, Any] | None:
  """Extract string JSON fields when the model appends trailing garbage after a valid object."""
  if not text or "{" not in text:
    return None
  extracted: dict[str, Any] = {}
  for field in fields:
    pattern = rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"'
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
      continue
    raw = match.group(1)
    try:
      extracted[field] = json.loads(f'"{raw}"')
    except json.JSONDecodeError:
      extracted[field] = raw.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
  if required and not all(field in extracted for field in required):
    return None
  return extracted or None
