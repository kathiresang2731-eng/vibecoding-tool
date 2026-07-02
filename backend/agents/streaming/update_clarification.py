from __future__ import annotations

import re
from typing import Any

VAGUE_UPDATE_PHRASES = (
  "make it better",
  "make this better",
  "improve it",
  "improve this",
  "fix it",
  "fix this",
  "looks bad",
  "look bad",
  "doesn't work",
  "does not work",
  "not working",
  "something wrong",
  "update it",
  "change it",
)

FILE_HINT_RE = re.compile(
  r"\b(?:src/)?[a-z0-9_./-]+\.(?:jsx|tsx|js|ts|html|css|json)\b",
  re.IGNORECASE,
)

REFERENTIAL_FOLLOWUP_MARKERS = (
  " it",
  " it.",
  " this",
  " that",
  " also",
  " same",
  " too",
  " those",
  " these",
  "instead",
  "as well",
  "like before",
  "like that",
)


def _prompt_tokens(prompt: str) -> set[str]:
  return set(re.findall(r"[a-z0-9]+", prompt.lower()))


def _has_file_or_component_hint(prompt: str) -> bool:
  if FILE_HINT_RE.search(prompt):
    return True
  tokens = _prompt_tokens(prompt)
  component_hints = {
    "header",
    "footer",
    "navbar",
    "nav",
    "sidebar",
    "hero",
    "dashboard",
    "modal",
    "button",
    "page",
    "home",
    "about",
    "login",
    "onboarding",
    "color",
    "colour",
    "theme",
    "font",
    "section",
    "menu",
    "pricing",
    "feature",
    "module",
    "modules",
    "layout",
    "background",
    "primary",
    "secondary",
    "report",
    "analytics",
    "auth",
    "crm",
  }
  return bool(tokens & component_hints)


def _has_structured_requirement(prompt: str) -> bool:
  cleaned = str(prompt or "").strip()
  if not cleaned:
    return False
  if len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", cleaned, flags=re.MULTILINE)) >= 2:
    return True
  lowered = cleaned.lower()
  requirement_markers = (
    "requirement",
    "requirements",
    "based on",
    "must have",
    "should have",
    "need to",
    "include ",
    "with modules",
    "with pages",
    "add module",
    "add page",
    "new module",
    "new page",
  )
  return any(marker in lowered for marker in requirement_markers)


def _is_referential_followup(prompt: str) -> bool:
  lowered = f" {prompt.lower()} "
  return any(marker in lowered for marker in REFERENTIAL_FOLLOWUP_MARKERS)


def check_streaming_update_clarification(
  prompt: str,
  *,
  intent: str,
  project_files: list[dict[str, Any]] | None = None,
  scoped_targets: list[str] | None = None,
  has_conversation_context: bool = False,
) -> str | None:
  """
  Return a clarifying question when an update request is too vague to safely parallelize.
  Does not call the LLM — deterministic guard only.
  """
  if intent != "website_update":
    return None
  cleaned = str(prompt or "").strip()
  if not cleaned:
    return "Which file, page, or component should I update?"
  lowered = cleaned.lower()
  if scoped_targets:
    return None
  if _has_structured_requirement(cleaned):
    return None
  if _has_file_or_component_hint(cleaned):
    return None
  if has_conversation_context and _is_referential_followup(cleaned):
    return None
  if any(phrase in lowered for phrase in VAGUE_UPDATE_PHRASES):
    return (
      "Your update request is a bit broad. Which page, component, or file should I change, "
      "and what should it look or behave like after the update?"
    )
  word_count = len(re.findall(r"\w+", cleaned))
  if word_count < 5 and not _has_file_or_component_hint(cleaned):
    if has_conversation_context:
      return None
    return (
      "Please specify which part of the website to update — for example the header, a page name, "
      "or the exact behavior you want changed."
    )
  meaningful_paths = [
    str(item.get("path") or "")
    for item in project_files or []
    if isinstance(item, dict) and str(item.get("path") or "").startswith(("src/", "index.html"))
  ]
  if meaningful_paths and word_count < 8 and not _has_file_or_component_hint(cleaned):
    if has_conversation_context:
      return None
    return (
      "Which file or UI area should I edit? Mention a page or component name so I can apply a scoped update."
    )
  return None
