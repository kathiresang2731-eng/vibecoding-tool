from __future__ import annotations

import re
from typing import Any

from ...artifacts import normalize_generated_file_code
from ..constants import *
from ..file_ops import tool_files_to_artifact_files, unique_paths
from ..update_analysis import normalize_scoped_update_candidate_new_files, sanitize_pascal_component_name, scoped_list_items_from_prompt
from ..values import list_value, object_value, string_list, text_or_default
from .shared_constants import CONST_ARRAY_START_PATTERN, SCOPED_COUNT_WORDS, TIGER_CONTENT_VARIANTS

def parse_scoped_count_word(value: str) -> int:
  lowered = value.lower().strip()
  if lowered in SCOPED_COUNT_WORDS:
    return SCOPED_COUNT_WORDS[lowered]
  try:
    return max(1, min(12, int(lowered)))
  except ValueError:
    return 1


def expand_counted_content_items(count: int, noun: str) -> list[str]:
  noun_key = noun.lower().strip()
  if noun_key.startswith("tiger"):
    return TIGER_CONTENT_VARIANTS[:count]
  singular = noun_key[:-1] if noun_key.endswith("s") and len(noun_key) > 3 else noun_key
  titled = singular.replace("-", " ").title()
  return [f"{titled} {index + 1}" for index in range(count)]


def scoped_content_items_from_request(
  prompt: str,
  update_analysis: dict[str, Any],
  *,
  task: dict[str, Any] | None = None,
) -> list[str]:
  synthetic_task = task or {
    "prompt": prompt,
    "summary": text_or_default(update_analysis.get("summary"), ""),
  }
  counted_items = counted_scoped_content_items(prompt)
  if counted_items:
    return counted_items
  from .generation_parts.feature_ops import deterministic_feature_items_for_task
  items = deterministic_feature_items_for_task(synthetic_task, update_analysis)
  if items:
    return items

  cleaned: list[str] = []
  seen: set[str] = set()
  for line in prompt.splitlines():
    match = re.match(r"^\s*(?:\d+[\.\)]|[-*•])\s*(.+)$", line.strip())
    if not match:
      continue
    label = re.sub(r"\s+", " ", match.group(1).replace("\u2019", "'")).strip(" .;:-")
    if not label or len(label.split()) > 8:
      continue
    key = label.lower()
    if key in seen:
      continue
    seen.add(key)
    cleaned.append(label[:80])
  if cleaned:
    return cleaned

  return counted_scoped_content_items(prompt)


def counted_scoped_content_items(value: str) -> list[str]:
  count_match = re.search(
    r"(?:add|include|insert|append|show|display)\s+"
    r"(?P<count>one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:(?:different|unique|new)\s+)?(?P<noun>[a-z][a-z0-9-]*)",
    value,
    re.IGNORECASE,
  )
  if count_match:
    return expand_counted_content_items(
      parse_scoped_count_word(count_match.group("count")),
      count_match.group("noun"),
    )
  article_match = re.search(
    r"(?:add|include|insert|append|show|display)\s+"
    r"(?:a|an|the)\s+(?P<noun>[a-z][a-z0-9-]*)",
    value,
    re.IGNORECASE,
  )
  if article_match:
    return expand_counted_content_items(1, article_match.group("noun"))
  return []


def scoped_update_requests_list_addition(
  prompt: str,
  update_analysis: dict[str, Any],
  items: list[str],
) -> bool:
  if not items:
    return False
  lowered = prompt.lower()
  layout_markers = (
    "redesign",
    "rearrange",
    "restyle",
    "change layout",
    "change color",
    "navbar",
    "footer",
    "hero section",
  )
  if any(marker in lowered for marker in layout_markers):
    return False
  return any(
    marker in lowered
    for marker in ("add", "include", "insert", "append", "more", "another", "extra")
  )


def find_const_array_close_index(content: str, open_bracket_index: int) -> int:
  depth = 0
  for index in range(open_bracket_index, len(content)):
    char = content[index]
    if char == "[":
      depth += 1
    elif char == "]":
      depth -= 1
      if depth == 0:
        return index
  return -1


def score_const_array_name(name: str, prompt: str, path: str) -> int:
  request = prompt.lower()
  path_key = path.lower()
  name_key = name.lower()
  score = 0
  request_tokens = {token for token in re.findall(r"[a-z0-9]+", request) if len(token) >= 3}
  name_tokens = {token for token in re.findall(r"[a-z0-9]+", name_key) if len(token) >= 3}
  score += len(request_tokens & name_tokens) * 40
  if name_key in request:
    score += 100
  singular = name_key.rstrip("s")
  if singular and singular in request:
    score += 60
  if name_key in path_key or singular in path_key:
    score += 80
  return score


def parse_max_id_from_array_body(body: str) -> int:
  ids = [int(value) for value in re.findall(r"\bid\s*:\s*(\d+)", body)]
  return max(ids) if ids else 0


def sample_object_from_array_body(body: str) -> str:
  depth = 0
  start = -1
  for index, char in enumerate(body):
    if char == "{":
      if depth == 0:
        start = index
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0 and start >= 0:
        return body[start : index + 1]
  return ""


def build_array_object_entry(*, sample: str, item_label: str, item_id: int) -> str:
  if not sample:
    return (
      f"    {{ id: {item_id}, name: \"{js_string_literal(item_label)}\", "
      f"description: \"{js_string_literal(component_item_description(item_label))}\" }}"
    )
  entry = sample
  if re.search(r"\bid\s*:", entry):
    entry = re.sub(r"\bid\s*:\s*\d+", f"id: {item_id}", entry, count=1)
  for field in ("name", "title", "label"):
    if re.search(rf"\b{field}\s*:", entry):
      entry = re.sub(
        rf"\b{field}\s*:\s*\"[^\"]*\"",
        f'{field}: "{js_string_literal(item_label)}"',
        entry,
        count=1,
      )
      break
  else:
    trimmed = entry.rstrip()
    if trimmed.endswith("}"):
      inner = trimmed[:-1].rstrip()
      separator = "" if inner.endswith(",") else ", "
      entry = f"{inner}{separator}name: \"{js_string_literal(item_label)}\" }}"
  return "    " + entry.strip()


def append_items_to_const_array_content(
  content: str,
  items: list[str],
  *,
  prompt: str,
  path: str,
) -> str | None:
  best: tuple[int, int, int] | None = None
  for match in CONST_ARRAY_START_PATTERN.finditer(content):
    open_bracket = match.end() - 1
    close_bracket = find_const_array_close_index(content, open_bracket)
    if close_bracket < 0:
      continue
    score = score_const_array_name(match.group("name"), prompt, path)
    if score <= 0:
      continue
    candidate = (score, open_bracket, close_bracket)
    if best is None or candidate[0] > best[0]:
      best = candidate
  if best is None:
    return None

  _, open_bracket, close_bracket = best
  body = content[open_bracket + 1 : close_bracket]
  sample = sample_object_from_array_body(body.strip())
  next_id = parse_max_id_from_array_body(body)
  existing_names = {
    value.lower()
    for value in re.findall(r'\b(?:name|title|label)\s*:\s*"([^"]*)"', body, re.IGNORECASE)
  }
  new_entries: list[str] = []
  for item in items:
    if item.lower() in existing_names:
      continue
    next_id += 1
    new_entries.append(build_array_object_entry(sample=sample, item_label=item, item_id=next_id))
  if not new_entries:
    return None

  trimmed_body = body.strip()
  if not trimmed_body:
    prefix = "\n"
  elif trimmed_body.endswith(","):
    prefix = "\n"
  else:
    prefix = ",\n"
  insertion = prefix + ",\n".join(new_entries) + "\n  "
  return content[:close_bracket] + insertion + content[close_bracket:]
