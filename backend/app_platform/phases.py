from __future__ import annotations

from typing import Any

PLATFORM_PHASES: tuple[dict[str, Any], ...] = (
  {
    "id": 0,
    "name": "Harness stabilization",
    "focus": "Live runtime trace, unified v1 events, hierarchical LangGraph MAS",
    "status": "active",
    "exit_criteria": "Generation reliable; one event schema; live trace is source of truth",
  },
  {
    "id": 1,
    "name": "Universal file tools + patch engine",
    "focus": "APPLY_PATCH, READ_FILE_RANGE, LIST_DIR, GLOB_SEARCH",
    "status": "in_progress",
    "exit_criteria": "Edit any repo file safely with patch-first workflow",
  },
  {
    "id": 2,
    "name": "Context engine",
    "focus": "Index + Qdrant + SEARCH_CODEBASE",
    "status": "planned",
    "exit_criteria": "Large-repo semantic retrieval works",
  },
  {
    "id": 3,
    "name": "Terminal + git + test runner",
    "focus": "RUN_TERMINAL, GIT_STATUS, RUN_TESTS",
    "status": "planned",
    "exit_criteria": "Agent runs tests and fixes failures in sandbox",
  },
  {
    "id": 4,
    "name": "MCP host + policy engine",
    "focus": "MCP_CALL_TOOL, approval tiers, audit replay",
    "status": "planned",
    "exit_criteria": "External tools with permissions",
  },
  {
    "id": 5,
    "name": "IDE/CLI affordances",
    "focus": "WebSocket, worktrees, run replay",
    "status": "planned",
    "exit_criteria": "Extension-ready API for CLI and IDE clients",
  },
)


def current_platform_phase() -> dict[str, Any]:
  for phase in PLATFORM_PHASES:
    if phase.get("status") == "active":
      return dict(phase)
  for phase in PLATFORM_PHASES:
    if phase.get("status") == "in_progress":
      return dict(phase)
  return dict(PLATFORM_PHASES[0])
