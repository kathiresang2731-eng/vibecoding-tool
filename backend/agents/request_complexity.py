from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .prompt_context import current_user_prompt


ADAPTIVE_ROUTE_TINY_CHAT = "tiny_chat"
ADAPTIVE_ROUTE_CONVERSATION = "conversation"
ADAPTIVE_ROUTE_ROUTING_PENDING = "routing_pending"
ADAPTIVE_ROUTE_SMALL_CODE = "small_code"
ADAPTIVE_ROUTE_TARGETED_UPDATE = "targeted_update"
ADAPTIVE_ROUTE_FEATURE_UPDATE = "feature_update"
ADAPTIVE_ROUTE_LARGE_PROJECT = "large_project"
ADAPTIVE_ROUTE_FULL_GENERATION = "full_generation"


@dataclass(frozen=True)
class AdaptiveRequestRoute:
  route: str
  workflow: str
  reason: str
  context_mode: str
  max_existing_files: int
  max_new_files: int
  context_max_files: int
  context_max_chars: int
  use_project_context: bool
  use_chat_history: bool
  use_memory_context: bool
  use_parallel_workers: bool
  use_model_for_conversation: bool = True

  def to_dict(self) -> dict[str, Any]:
    return asdict(self)


def classify_adaptive_request_route(
  prompt: str,
  *,
  intent: str | None = None,
  project_files: list[dict[str, Any]] | None = None,
  attachments: list[dict[str, Any]] | None = None,
) -> AdaptiveRequestRoute:
  text = current_user_prompt(str(prompt or "")).strip()
  lowered = _normalize(text)
  intent_name = str(intent or "").strip().lower()
  has_attachments = bool(attachments)
  file_count = len([item for item in (project_files or []) if isinstance(item, dict)])

  if (intent_name == "greeting" or _looks_like_brief_greeting(text)) and not has_attachments:
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_TINY_CHAT,
      workflow="llm_conversation",
      reason="Short conversation-only turn; use the greeting LLM without project context or artifact generation.",
      context_mode="none",
      max_existing_files=0,
      max_new_files=0,
      context_max_files=0,
      context_max_chars=0,
      use_project_context=False,
      use_chat_history=False,
      use_memory_context=False,
      use_parallel_workers=False,
      use_model_for_conversation=True,
    )

  if intent_name in {
    "question",
    "general_query",
    "web_search",
    "project_info",
    "needs_more_detail",
    "needs_confirmation",
  }:
    use_project_context = intent_name == "project_info"
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_CONVERSATION,
      workflow="grounded_web_search" if intent_name == "web_search" else "llm_conversation",
      reason=(
        "Read-only user turn; answer without starting artifact generation or project file updates."
      ),
      context_mode="current_project_read_only" if use_project_context else "conversation_only",
      max_existing_files=8 if use_project_context else 0,
      max_new_files=0,
      context_max_files=8 if use_project_context else 0,
      context_max_chars=24_000 if use_project_context else 0,
      use_project_context=use_project_context,
      use_chat_history=use_project_context,
      use_memory_context=use_project_context,
      use_parallel_workers=False,
      use_model_for_conversation=True,
    )

  if not intent_name:
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_ROUTING_PENDING,
      workflow="llm_intent_routing",
      reason="Intent is intentionally deferred to the LLM router before selecting a conversation or artifact workflow.",
      context_mode="routing_context",
      max_existing_files=0,
      max_new_files=0,
      context_max_files=0,
      context_max_chars=0,
      use_project_context=False,
      use_chat_history=True,
      use_memory_context=True,
      use_parallel_workers=False,
      use_model_for_conversation=True,
    )

  if intent_name == "simple_code":
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_SMALL_CODE,
      workflow="minimal_standalone_code",
      reason="Standalone code request; use one compact artifact call and never create website scaffold files.",
      context_mode="code_only_minimal",
      max_existing_files=1,
      max_new_files=1,
      context_max_files=1,
      context_max_chars=8_000,
      use_project_context=False,
      use_chat_history=False,
      use_memory_context=True,
      use_parallel_workers=False,
    )

  if intent_name == "website_update":
    if _is_large_project_request(lowered):
      return AdaptiveRequestRoute(
        route=ADAPTIVE_ROUTE_LARGE_PROJECT,
        workflow="plan_file_groups_parallel_workers",
        reason="Broad update request; split into planned file groups with validation before commit.",
        context_mode="large_update_index_and_selected_files",
        max_existing_files=12,
        max_new_files=6,
        context_max_files=18,
        context_max_chars=120_000,
        use_project_context=True,
        use_chat_history=False,
        use_memory_context=True,
        use_parallel_workers=True,
      )
    if _looks_like_feature_scope(lowered):
      return AdaptiveRequestRoute(
        route=ADAPTIVE_ROUTE_FEATURE_UPDATE,
        workflow="staged_scoped_patches",
        reason="Bounded feature update; use selected files and staged patch validation.",
        context_mode="feature_selected_files",
        max_existing_files=8,
        max_new_files=2,
        context_max_files=8,
        context_max_chars=24_000,
        use_project_context=True,
        use_chat_history=False,
        use_memory_context=True,
        use_parallel_workers=False,
      )
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_TARGETED_UPDATE,
      workflow="scoped_patch_only",
      reason="Small existing-project update; keep patch scope tight.",
      context_mode="targeted_selected_files",
      max_existing_files=4,
      max_new_files=0,
      context_max_files=4,
      context_max_chars=12_000,
      use_project_context=True,
      use_chat_history=False,
      use_memory_context=True,
      use_parallel_workers=False,
    )

  if intent_name == "website_generation":
    large_generation = _is_large_project_request(lowered) or (file_count > 0 and _looks_like_multi_part_request(lowered))
    if large_generation:
      return AdaptiveRequestRoute(
        route=ADAPTIVE_ROUTE_LARGE_PROJECT,
        workflow="plan_file_groups_parallel_workers",
        reason="Large generation request; split implementation across coordinated file workers.",
        context_mode="large_generation_plan",
        max_existing_files=12,
        max_new_files=12,
        context_max_files=18,
        context_max_chars=120_000,
        use_project_context=True,
        use_chat_history=True,
        use_memory_context=True,
        use_parallel_workers=True,
      )
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_FULL_GENERATION,
      workflow="multi_worker_generation",
      reason="New website/app generation; use shared contract and integration validation.",
      context_mode="file_index_and_generation_brief",
      max_existing_files=8,
      max_new_files=12,
      context_max_files=12,
      context_max_chars=72_000,
      use_project_context=True,
      use_chat_history=True,
      use_memory_context=True,
      use_parallel_workers=True,
    )

  return AdaptiveRequestRoute(
    route=ADAPTIVE_ROUTE_TARGETED_UPDATE,
    workflow="scoped_patch_or_clarify",
    reason="Default safe route; use bounded context and clarify before broad rewrites.",
    context_mode="targeted_selected_files",
    max_existing_files=4,
    max_new_files=0,
    context_max_files=4,
    context_max_chars=12_000,
    use_project_context=True,
    use_chat_history=False,
    use_memory_context=True,
    use_parallel_workers=False,
  )


def adaptive_route_dict(
  prompt: str,
  *,
  intent: str | None = None,
  project_files: list[dict[str, Any]] | None = None,
  attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
  route = classify_adaptive_request_route(
    prompt,
    intent=intent,
    project_files=project_files,
    attachments=attachments,
  ).to_dict()
  project_file_count = len([item for item in (project_files or []) if isinstance(item, dict)])
  if route.get("use_project_context"):
    route["project_file_count"] = project_file_count
    route["context_budget_note"] = (
      "max_existing_files/context_max_files are scoped context limits for the model, "
      "not the total number of files in the project."
    )
  return route


def _normalize(text: str) -> str:
  return " ".join(text.strip().lower().replace("!", " ").replace(".", " ").split())


def _looks_like_brief_greeting(text: str) -> bool:
  normalized = _normalize(text)
  if not normalized or len(normalized) > 32:
    return False
  if re.fullmatch(r"h[iy]+(?:\s+there)?", normalized):
    return True
  if re.fullmatch(r"he+y+(?:\s+there)?", normalized):
    return True
  if re.fullmatch(r"hello+(?:\s+there)?", normalized):
    return True
  if re.fullmatch(r"good\s+(morning|afternoon|evening)", normalized):
    return True
  return False


def _is_large_project_request(lowered: str) -> bool:
  if not lowered:
    return False
  if len(lowered) > 2_500 or lowered.count("\n") >= 10:
    return True
  mentioned_paths = re.findall(
    r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)+\.(?:js|jsx|ts|tsx|css|html|json|py)\b",
    lowered,
  )
  if len(set(mentioned_paths)) >= 4:
    return True
  list_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", lowered))
  if list_items >= 5:
    return True
  structural_scope_hits = len(
    re.findall(
      r"\b(all|every|entire|whole|complete|full|sitewide|site-wide|multipage|multi-page|end-to-end|migration|redesign|refactor)\b",
      lowered,
    )
  )
  surface_hits = len(
    re.findall(
      r"\b(page|pages|screen|screens|component|components|module|modules|layout|layouts|route|routes|section|sections|panel|panels)\b",
      lowered,
    )
  )
  if structural_scope_hits >= 2:
    return True
  if structural_scope_hits >= 1 and surface_hits >= 2:
    return True
  return False


def _looks_like_feature_scope(lowered: str) -> bool:
  if not lowered:
    return False
  explicit_paths = re.findall(
    r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)+\.(?:js|jsx|ts|tsx|css|html|json|py)\b",
    lowered,
  )
  page_mentions = len(re.findall(r"\b(page|screen|section|module|component|chart|table|form|modal|drawer|dashboard|panel|card)\b", lowered))
  control_mentions = len(re.findall(r"\b(button|form|modal|drawer|login|signup|navigation|route|link|handler|cta)\b", lowered))
  structural_clauses = len(re.findall(r"\b(below|above|under|inside|next to|between|replace with|instead of)\b", lowered))
  if len(set(explicit_paths)) >= 2:
    return True
  if page_mentions >= 2:
    return True
  if control_mentions >= 1 and page_mentions >= 1:
    return True
  if control_mentions >= 2:
    return True
  if page_mentions >= 1 and structural_clauses >= 1:
    return True
  if len(lowered) >= 140 and lowered.count(" and ") >= 1:
    return True
  return False


def _looks_like_multi_part_request(lowered: str) -> bool:
  if not lowered:
    return False
  explicit_paths = re.findall(
    r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)+\.(?:js|jsx|ts|tsx|css|html|json|py)\b",
    lowered,
  )
  list_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", lowered))
  return len(set(explicit_paths)) >= 2 or list_items >= 3 or len(lowered) >= 180


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
  return any(marker in text for marker in markers)
