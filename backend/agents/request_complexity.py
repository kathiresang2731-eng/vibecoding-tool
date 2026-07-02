from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .prompt_context import current_user_prompt
from .project_workspace import is_standalone_code_project


ADAPTIVE_ROUTE_TINY_CHAT = "tiny_chat"
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


_CODE_REQUEST_MARKERS = (
  "write a code",
  "write code",
  "generate code",
  "create code",
  "give me code",
  "write a program",
  "generate a program",
  "create a program",
  "java program",
  "python program",
  "standalone code",
  "standalone program",
)

_CODE_TASK_MARKERS = (
  "algorithm",
  "script",
  "function",
  "program",
  "number",
  "prime",
  "neon",
  "armstrong",
  "palindrome",
  "fibonacci",
  "factorial",
  "reverse",
  "sort",
  "array",
  "string",
  "matrix",
  "calculator",
  "pattern",
)

_CODE_LANGUAGE_MARKERS = (
  "python",
  "java",
  "javascript",
  "typescript",
  "rust",
  "golang",
  " go ",
  "c++",
  "c#",
  "php",
  "ruby",
  "kotlin",
  "swift",
)

_WEB_CONTEXT_MARKERS = (
  "website",
  "web site",
  "web app",
  "webapp",
  "landing page",
  "frontend",
  "react app",
  "vite",
  "dashboard",
  "page",
  "this site",
  "this website",
)

_UPDATE_MARKERS = (
  "update ",
  "change ",
  "add ",
  "fix ",
  "edit ",
  "modify ",
  "replace ",
  "remove ",
  "debug ",
  "resolve ",
  "simplify",
  "simplified",
  "complicated",
  "comments",
  "version",
)

_FEATURE_MARKERS = (
  "new feature",
  "add feature",
  "create feature",
  "add page",
  "new page",
  "add modal",
  "add tab",
  "add form",
  "integration",
  "auth",
  "login",
  "signup",
  "api",
  "database",
  "backend",
)

_LARGE_SCOPE_MARKERS = (
  "entire website",
  "whole website",
  "all pages",
  "every page",
  "complete website",
  "complete app",
  "full stack",
  "full-stack",
  "admin panel",
  "multi page",
  "multipage",
  "end to end",
  "enterprise",
  "redesign",
  "refactor",
  "migration",
  "responsive across",
  "site-wide",
  "sitewide",
  "single static page",
  "missing modules",
  "based on requirement",
)

_FULL_REPLACE_MARKERS = (
  "from scratch",
  "new project",
  "brand new",
  "full generation",
  "generate full",
  "rebuild",
  "regenerate",
)

_TINY_CHAT_VALUES = {
  "hi",
  "hii",
  "hiii",
  "hello",
  "hey",
  "hey there",
  "hello there",
  "good morning",
  "good afternoon",
  "good evening",
  "thanks",
  "thank you",
  "ok",
  "okay",
}


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

  if not has_attachments and _is_tiny_chat(lowered):
    return AdaptiveRequestRoute(
      route=ADAPTIVE_ROUTE_TINY_CHAT,
      workflow="deterministic_conversation",
      reason="Short conversation-only turn; no project context or model call is required.",
      context_mode="none",
      max_existing_files=0,
      max_new_files=0,
      context_max_files=0,
      context_max_chars=0,
      use_project_context=False,
      use_chat_history=False,
      use_memory_context=False,
      use_parallel_workers=False,
      use_model_for_conversation=False,
    )

  if (
    intent_name == "simple_code"
    or _looks_like_small_code_request(lowered)
    or (is_standalone_code_project(project_files) and not _has_any(lowered, _WEB_CONTEXT_MARKERS))
  ):
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

  update_intent = intent_name == "website_update" or _has_any(lowered, _UPDATE_MARKERS)
  if update_intent:
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
        use_chat_history=True,
        use_memory_context=True,
        use_parallel_workers=True,
      )
    if _has_any(lowered, _FEATURE_MARKERS):
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
        use_chat_history=True,
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
      use_chat_history=True,
      use_memory_context=True,
      use_parallel_workers=False,
    )

  if intent_name == "website_generation" or _looks_like_generation_request(lowered):
    large_generation = _is_large_project_request(lowered) or (file_count > 0 and _has_any(lowered, _FULL_REPLACE_MARKERS))
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
    use_chat_history=True,
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
  return classify_adaptive_request_route(
    prompt,
    intent=intent,
    project_files=project_files,
    attachments=attachments,
  ).to_dict()


def _normalize(text: str) -> str:
  return " ".join(text.strip().lower().replace("!", " ").replace(".", " ").split())


def _is_tiny_chat(lowered: str) -> bool:
  if lowered in _TINY_CHAT_VALUES:
    return True
  if len(lowered) <= 32 and any(lowered.startswith(value) for value in ("hi", "hello", "hey")):
    return not _looks_like_generation_request(lowered) and not _looks_like_small_code_request(lowered)
  return False


def _looks_like_small_code_request(lowered: str) -> bool:
  if not lowered or _has_any(lowered, _WEB_CONTEXT_MARKERS):
    return False
  if _has_any(lowered, _CODE_REQUEST_MARKERS):
    return True
  wants_code_action = any(marker in lowered for marker in ("write ", "create ", "generate ", "make ", "give me "))
  has_code_target = _has_any(lowered, _CODE_TASK_MARKERS)
  has_language = _has_any(f" {lowered} ", _CODE_LANGUAGE_MARKERS)
  return wants_code_action and has_code_target and (has_language or "code" in lowered or "program" in lowered)


def _looks_like_generation_request(lowered: str) -> bool:
  if not lowered:
    return False
  return any(
    marker in lowered
    for marker in (
      "build ",
      "create ",
      "generate ",
      "regenerate",
      "rebuild",
      "make a website",
      "make an app",
      "new website",
      "landing page",
      "web app",
      "website",
    )
  )


def _is_large_project_request(lowered: str) -> bool:
  if not lowered:
    return False
  if len(lowered) > 2_500 or lowered.count("\n") >= 10:
    return True
  if _has_any(lowered, _LARGE_SCOPE_MARKERS):
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
  return False


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
  return any(marker in text for marker in markers)
