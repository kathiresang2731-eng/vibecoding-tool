"""Helpers for runtime loop tests under hierarchical LangGraph topology."""

from __future__ import annotations

BOOTSTRAP_ACTION = "RUN_PARALLEL_PROJECT_BOOTSTRAP"
BOOTSTRAP_TOOLS = ["READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY"]


def generation_action_history() -> list[str]:
  return [
    BOOTSTRAP_ACTION,
    "RUN_PROMPT_ANALYST",
    "RUN_PLANNER",
    "RUN_CODE_AGENT",
    "MATERIALIZE_CANDIDATE_FILES",
    "VALIDATE_PROJECT_ARTIFACT",
    "BUILD_STAGED_PROJECT_PREVIEW",
    "RUN_PREVIEW_VISUAL_QA",
    "PERSIST_PROJECT_MEMORY",
  ]


def scoped_update_action_history() -> list[str]:
  return [
    BOOTSTRAP_ACTION,
    "RUN_UPDATE_ANALYST",
    "RUN_SCOPED_UPDATE_AGENT",
    "MATERIALIZE_CANDIDATE_FILES",
    "VALIDATE_PROJECT_ARTIFACT",
    "BUILD_STAGED_PROJECT_PREVIEW",
    "RUN_PREVIEW_VISUAL_QA",
    "PERSIST_PROJECT_MEMORY",
  ]


def scoped_update_action_prefix() -> list[str]:
  return scoped_update_action_history()[:4]


def bootstrap_mas_action() -> str:
  return BOOTSTRAP_ACTION


def assert_bootstrap_mas_step(step: dict) -> None:
  action = str(step.get("action") or "")
  assert action in {BOOTSTRAP_ACTION, "parallel_project_bootstrap"}


def assert_bootstrap_tool_calls(calls: list[str]) -> None:
  assert BOOTSTRAP_TOOLS[0] in calls
  assert BOOTSTRAP_TOOLS[1] in calls
  assert calls.index(BOOTSTRAP_TOOLS[0]) < calls.index(BOOTSTRAP_TOOLS[1]) or calls.index(BOOTSTRAP_TOOLS[1]) < calls.index(BOOTSTRAP_TOOLS[0])
