from __future__ import annotations

import re

from backend.agents.request_understanding import (
  looks_like_underspecified_update_request,
)

WEBSITE_SPEC_MARKERS = (
  "website",
  "web app",
  "webapp",
  "dashboard",
  "onboarding",
  "backend",
  "frontend",
  "api",
  "color",
  "colour",
  "channel",
  "python",
  "react",
  "auth",
  "ccaas",
  "whatsapp",
  "instagram",
  "webchat",
  "settings",
  "report",
  "operations",
  "full stack",
  "full-stack",
)

SIMPLE_CODE_WEB_CONTEXT_MARKERS = (
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

SIMPLE_CODE_REQUEST_MARKERS = (
  "write a code",
  "write code",
  "generate code",
  "create code",
  "give me code",
  "provide code",
  "provide a code",
  "write a program",
  "generate a program",
  "create a program",
  "provide a program",
  "java program",
  "python program",
  "standalone code",
  "standalone program",
)

SIMPLE_CODE_TASK_MARKERS = (
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

SIMPLE_CODE_LANGUAGE_MARKERS = (
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

DOCUMENT_FILE_MARKERS = (
  ".md",
  ".markdown",
  ".txt",
  ".csv",
  ".pdf",
  "readme",
  "documentation",
  "document",
  "docs",
  "report",
  "proposal",
  "brief",
  "checklist",
  "runbook",
  "sop",
)

DOCUMENT_ACTION_MARKERS = (
  "write ",
  "create ",
  "generate ",
  "make ",
  "draft ",
  "prepare ",
  "save ",
  "export ",
)

RESEARCH_PLANNING_MARKERS = (
  "research",
  "plan",
  "planning",
  "roadmap",
  "strategy",
  "compare",
  "analysis",
  "analyze",
  "brainstorm",
  "outline",
)

TIME_SENSITIVE_RESEARCH_MARKERS = (
  "latest",
  "current",
  "today",
  "recent",
  "2026",
  "news",
  "price",
  "pricing",
  "release",
  "version",
  "web search",
  "search the web",
  "online",
  "sources",
)

def looks_like_simple_code_request(lowered_prompt: str) -> bool:
  if any(marker in lowered_prompt for marker in SIMPLE_CODE_WEB_CONTEXT_MARKERS):
    return False
  if any(marker in lowered_prompt for marker in SIMPLE_CODE_REQUEST_MARKERS):
    return True
  wants_code_action = any(marker in lowered_prompt for marker in ("write ", "create ", "generate ", "make ", "give me ", "provide "))
  has_code_target = any(marker in lowered_prompt for marker in SIMPLE_CODE_TASK_MARKERS)
  has_language = any(marker in f" {lowered_prompt} " for marker in SIMPLE_CODE_LANGUAGE_MARKERS)
  return wants_code_action and has_code_target and (has_language or "code" in lowered_prompt or "program" in lowered_prompt)


def looks_like_document_artifact_request(lowered_prompt: str) -> bool:
  if looks_like_website_generation_request(lowered_prompt):
    return False
  if any(marker in lowered_prompt for marker in SIMPLE_CODE_WEB_CONTEXT_MARKERS):
    return False
  wants_file = any(marker in lowered_prompt for marker in DOCUMENT_FILE_MARKERS)
  wants_action = any(marker in lowered_prompt for marker in DOCUMENT_ACTION_MARKERS)
  asks_to_save_research = any(marker in lowered_prompt for marker in RESEARCH_PLANNING_MARKERS) and any(marker in lowered_prompt for marker in ("save as", "as markdown", "as md", "as csv", "as txt", "as pdf", "file"))
  return (wants_file and wants_action) or asks_to_save_research


def looks_like_research_or_planning_request(lowered_prompt: str) -> bool:
  if looks_like_website_generation_request(lowered_prompt):
    return False
  return any(marker in lowered_prompt for marker in RESEARCH_PLANNING_MARKERS)


def looks_like_time_sensitive_research_request(lowered_prompt: str) -> bool:
  return looks_like_research_or_planning_request(lowered_prompt) and any(
    marker in lowered_prompt for marker in TIME_SENSITIVE_RESEARCH_MARKERS
  )


def looks_like_website_generation_request(lowered_prompt: str) -> bool:
  if not lowered_prompt:
    return False
  update_markers = ("update ", "change ", "fix ", "edit ", "modify ", "replace ", "remove ", "resolve ", "patch ")
  if any(marker in lowered_prompt for marker in update_markers):
    return False
  wants_build = any(marker in lowered_prompt for marker in ("build ", "create ", "generate", "regenerate", "rebuild", "make "))
  if not wants_build:
    return False
  website_hits = sum(1 for marker in WEBSITE_SPEC_MARKERS if marker in lowered_prompt)
  structured_items = len(re.findall(r"(?:^|\s)(?:[-*]|->|\d+[.)])\s+", lowered_prompt))
  wants_site = any(
    marker in lowered_prompt
    for marker in ("website", "web site", "web app", "webapp", "frontend", "react app", "crm", "dashboard", "landing page", "requirement", "requirements")
  )
  return wants_site and (website_hits >= 2 or len(lowered_prompt) > 80 or structured_items >= 3 or "based on requirement" in lowered_prompt)


def looks_like_project_file_update(lowered_prompt: str) -> bool:
  if any(secret in lowered_prompt for secret in (".env", "env.example", "environment file")):
    return True
  return bool(re.search(r"\b(?:src/)?[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*\.(?:js|jsx|ts|tsx|css|html|json|py|java|go|php|rb|sql|env)\b", lowered_prompt))
