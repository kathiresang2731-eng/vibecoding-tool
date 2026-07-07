from __future__ import annotations

import re
from typing import Any

from ....artifacts import normalize_generated_file_code
from ...values import list_value, object_value, string_list, text_or_default
from ..content_parts import (
  append_items_to_const_array_content,
  scoped_content_items_from_request,
  scoped_update_requests_list_addition,
  score_const_array_name,
)
from ..shared_constants import CONST_ARRAY_START_PATTERN
from .feature_ops import component_item_description
from .repair_ops import (
  deterministic_created_component_content_changes,
  deterministic_interaction_modal_fix_changes,
  deterministic_navigation_interaction_fix_changes,
  deterministic_onboarding_chat_update_changes,
  deterministic_undefined_name_runtime_fix_changes,
  deterministic_undefined_reference_fix_changes,
)

def deterministic_existing_list_content_update_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  task: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
  items = scoped_content_items_from_request(prompt, update_analysis, task=task)
  if not scoped_update_requests_list_addition(prompt, update_analysis, items):
    return []
  candidate_paths = set(string_list(update_analysis.get("candidate_files"), []))
  if not candidate_paths:
    return []

  best_match: tuple[int, str, str] | None = None
  for file_item in existing_files:
    path = text_or_default(file_item.get("path"), "")
    content = text_or_default(file_item.get("content"), "")
    if path not in candidate_paths or not path.endswith((".jsx", ".tsx", ".js", ".ts")):
      continue
    updated = append_items_to_const_array_content(content, items, prompt=prompt, path=path)
    if not updated or updated == content:
      continue
    score = score_const_array_name("", prompt, path) + len(items) * 5
    for match in CONST_ARRAY_START_PATTERN.finditer(content):
      score = max(score, score_const_array_name(match.group("name"), prompt, path))
    candidate = (score, path, updated)
    if best_match is None or candidate[0] > best_match[0]:
      best_match = candidate
  if best_match is None:
    return []
  _, path, updated = best_match
  return [{"path": path, "content": normalize_generated_file_code(path, updated)}]


def collect_deterministic_scoped_update_fallback_changes(
  *,
  prompt: str,
  update_analysis: dict[str, Any],
  existing_files: list[dict[str, str]],
  task: dict[str, Any] | None = None,
  working_files: list[dict[str, str]] | None = None,
  created_candidate_paths: list[str] | None = None,
) -> tuple[list[dict[str, str]], str]:
  synthetic_task = task or {
    "prompt": prompt,
    "summary": text_or_default(update_analysis.get("summary"), ""),
  }
  working = working_files or existing_files
  created = created_candidate_paths or []
  resolvers: list[tuple[str, Any]] = []
  if created:
    resolvers.append(
      (
        "created_component_content",
        lambda: deterministic_created_component_content_changes(
          task=synthetic_task,
          update_analysis=update_analysis,
          working_files=working,
          created_candidate_paths=created,
        ),
      )
    )
  resolvers.extend(
    [
      (
        "existing_list_content",
        lambda: deterministic_existing_list_content_update_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
          task=synthetic_task,
        ),
      ),
      (
        "navigation_interaction_wiring",
        lambda: deterministic_navigation_interaction_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "new_project_modal_interaction",
        lambda: deterministic_interaction_modal_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "onboarding_chat_flow",
        lambda: deterministic_onboarding_chat_update_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "undefined_reference_fix",
        lambda: deterministic_undefined_reference_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
      (
        "undefined_name_runtime_fix",
        lambda: deterministic_undefined_name_runtime_fix_changes(
          prompt=prompt,
          update_analysis=update_analysis,
          existing_files=existing_files,
        ),
      ),
    ]
  )
  if not created:
    resolvers.append(
      (
        "created_component_content",
        lambda: deterministic_created_component_content_changes(
          task=synthetic_task,
          update_analysis=update_analysis,
          working_files=working,
          created_candidate_paths=created,
        ),
      )
    )
  for fallback_kind, resolver in resolvers:
    changes = resolver()
    valid_changes = non_empty_deterministic_changes(changes)
    if valid_changes:
      return valid_changes, fallback_kind
  return [], ""


def non_empty_deterministic_changes(changes: Any) -> list[dict[str, str]]:
  valid: list[dict[str, str]] = []
  for item in list_value(changes):
    if not isinstance(item, dict):
      continue
    path = text_or_default(item.get("path"), "")
    content = item.get("content")
    if not isinstance(content, str):
      content = item.get("code")
    if not path or not isinstance(content, str) or not content.strip():
      continue
    valid.append({"path": path, "content": content})
  return valid
