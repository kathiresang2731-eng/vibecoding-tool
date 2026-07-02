from __future__ import annotations

from typing import Any

try:
  from ...agents.artifacts import ArtifactValidationError
  from ...local_workspace import LocalWorkspaceError
  from ...runtime import PreviewRuntimeError
  from ...storage import StorageError, UserContext
except ImportError:
  from agents.artifacts import ArtifactValidationError
  from local_workspace import LocalWorkspaceError
  from runtime import PreviewRuntimeError
  from storage import StorageError, UserContext

try:
  from ...agents.agent_tool_catalog import PLATFORM_TOOL_DESCRIPTIONS, WEBSITE_TOOL_DESCRIPTIONS
except ImportError:
  from agents.agent_tool_catalog import PLATFORM_TOOL_DESCRIPTIONS, WEBSITE_TOOL_DESCRIPTIONS

from .definitions import ToolDefinition, ToolExecutionError, ToolRuntimeContext
from .handlers import (
  build_project_preview_tool,
  build_staged_project_preview_tool,
  load_project_memory_tool,
  persist_project_memory_tool,
  read_project_files_tool,
  run_preview_visual_qa_tool,
  sync_local_project_tool,
  validate_project_artifact_tool,
  write_project_files_tool,
)
from .platform import (
  apply_patch_tool,
  glob_search_tool,
  list_dir_tool,
  read_file_range_tool,
  read_file_tool,
  search_codebase_tool,
  str_replace_tool,
)
from .execution_tools import (
  git_commit_tool,
  git_diff_tool,
  git_status_tool,
  run_lint_tool,
  run_terminal_tool,
  run_tests_tool,
)

def website_tool_registry() -> dict[str, ToolDefinition]:
  tools = [
    ToolDefinition(
      name="READ_PROJECT_FILES",
      description=WEBSITE_TOOL_DESCRIPTIONS["READ_PROJECT_FILES"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=read_project_files_tool,
    ),
    ToolDefinition(
      name="LOAD_PROJECT_MEMORY",
      description=WEBSITE_TOOL_DESCRIPTIONS["LOAD_PROJECT_MEMORY"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "namespace": {"type": "string"},
          "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=load_project_memory_tool,
    ),
    ToolDefinition(
      name="PERSIST_PROJECT_MEMORY",
      description=WEBSITE_TOOL_DESCRIPTIONS["PERSIST_PROJECT_MEMORY"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "namespace": {"type": "string"},
          "key": {"type": "string"},
          "kind": {"type": "string"},
          "content": {"type": "string"},
          "metadata": {"type": "object"},
        },
        "required": ["project_id", "key", "content"],
        "additionalProperties": False,
      },
      handler=persist_project_memory_tool,
    ),
    ToolDefinition(
      name="WRITE_PROJECT_FILES",
      description=WEBSITE_TOOL_DESCRIPTIONS["WRITE_PROJECT_FILES"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "files": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
              },
              "required": ["path", "content"],
              "additionalProperties": False,
            },
          },
          "allow_empty": {"type": "boolean"},
          "mode": {"type": "string", "enum": ["upsert", "replace_all"]},
          "allow_prune_missing": {"type": "boolean"},
          "reason": {"type": "string"},
        },
        "required": ["project_id", "files"],
        "additionalProperties": False,
      },
      handler=write_project_files_tool,
    ),
    ToolDefinition(
      name="VALIDATE_PROJECT_ARTIFACT",
      description=WEBSITE_TOOL_DESCRIPTIONS["VALIDATE_PROJECT_ARTIFACT"],
      parameters={
        "type": "object",
        "properties": {
          "generated_website": {"type": "object"},
        },
        "required": ["generated_website"],
        "additionalProperties": False,
      },
      handler=validate_project_artifact_tool,
    ),
    ToolDefinition(
      name="BUILD_PROJECT_PREVIEW",
      description=WEBSITE_TOOL_DESCRIPTIONS["BUILD_PROJECT_PREVIEW"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=build_project_preview_tool,
    ),
    ToolDefinition(
      name="BUILD_STAGED_PROJECT_PREVIEW",
      description=WEBSITE_TOOL_DESCRIPTIONS["BUILD_STAGED_PROJECT_PREVIEW"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "files": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
              },
              "required": ["path", "content"],
              "additionalProperties": False,
            },
          },
        },
        "required": ["project_id", "files"],
        "additionalProperties": False,
      },
      handler=build_staged_project_preview_tool,
    ),
    ToolDefinition(
      name="RUN_PREVIEW_VISUAL_QA",
      description=WEBSITE_TOOL_DESCRIPTIONS["RUN_PREVIEW_VISUAL_QA"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "status": {"type": "string"},
          "preview_url": {"type": "string"},
          "build_log": {"type": "string"},
          "operation": {"type": "string", "enum": ["generation", "update"]},
          "scope": {"type": "string", "enum": ["full", "targeted"]},
          "chat_session_id": {"type": "string"},
          "generation_run_id": {"type": "string"},
          "agent_run_id": {"type": "string"},
          "project_version_id": {"type": "string"},
          "route": {"type": "string"},
          "router_mode": {"type": "string", "enum": ["hash", "browser"]},
          "phase": {"type": "string", "enum": ["after", "baseline"]},
          "changed_paths": {"type": "array", "items": {"type": "string"}},
          "affected_routes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["project_id", "status"],
        "additionalProperties": False,
      },
      handler=run_preview_visual_qa_tool,
    ),
    ToolDefinition(
      name="SYNC_LOCAL_PROJECT",
      description=WEBSITE_TOOL_DESCRIPTIONS["SYNC_LOCAL_PROJECT"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "direction": {"type": "string", "enum": ["pull", "push"]},
          "allow_prune_missing": {"type": "boolean"},
        },
        "required": ["project_id", "direction"],
        "additionalProperties": False,
      },
      handler=sync_local_project_tool,
    ),
  ]
  return {tool.name: tool for tool in tools}


def platform_tool_registry() -> dict[str, ToolDefinition]:
  tools = [
    ToolDefinition(
      name="READ_FILE",
      description=PLATFORM_TOOL_DESCRIPTIONS["READ_FILE"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "path": {"type": "string"},
        },
        "required": ["project_id", "path"],
        "additionalProperties": False,
      },
      handler=read_file_tool,
    ),
    ToolDefinition(
      name="READ_FILE_RANGE",
      description=PLATFORM_TOOL_DESCRIPTIONS["READ_FILE_RANGE"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "path": {"type": "string"},
          "start_line": {"type": "integer", "minimum": 1},
          "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["project_id", "path"],
        "additionalProperties": False,
      },
      handler=read_file_range_tool,
    ),
    ToolDefinition(
      name="LIST_DIR",
      description=PLATFORM_TOOL_DESCRIPTIONS["LIST_DIR"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "path": {"type": "string"},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=list_dir_tool,
    ),
    ToolDefinition(
      name="GLOB_SEARCH",
      description=PLATFORM_TOOL_DESCRIPTIONS["GLOB_SEARCH"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "pattern": {"type": "string"},
          "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["project_id", "pattern"],
        "additionalProperties": False,
      },
      handler=glob_search_tool,
    ),
    ToolDefinition(
      name="SEARCH_CODEBASE",
      description=PLATFORM_TOOL_DESCRIPTIONS["SEARCH_CODEBASE"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "query": {"type": "string"},
          "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["project_id", "query"],
        "additionalProperties": False,
      },
      handler=search_codebase_tool,
    ),
    ToolDefinition(
      name="STR_REPLACE",
      description=PLATFORM_TOOL_DESCRIPTIONS["STR_REPLACE"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "path": {"type": "string"},
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
        },
        "required": ["project_id", "path", "old_string", "new_string"],
        "additionalProperties": False,
      },
      handler=str_replace_tool,
    ),
    ToolDefinition(
      name="APPLY_PATCH",
      description=PLATFORM_TOOL_DESCRIPTIONS["APPLY_PATCH"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "patches": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "path": {"type": "string"},
                "unified_diff": {"type": "string"},
              },
              "required": ["path", "unified_diff"],
              "additionalProperties": False,
            },
          },
        },
        "required": ["project_id", "patches"],
        "additionalProperties": False,
      },
      handler=apply_patch_tool,
    ),
    ToolDefinition(
      name="RUN_TERMINAL",
      description=PLATFORM_TOOL_DESCRIPTIONS["RUN_TERMINAL"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "command": {"type": "array", "items": {"type": "string"}},
          "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
        },
        "required": ["project_id", "command"],
        "additionalProperties": False,
      },
      handler=run_terminal_tool,
    ),
    ToolDefinition(
      name="GIT_STATUS",
      description=PLATFORM_TOOL_DESCRIPTIONS["GIT_STATUS"],
      parameters={
        "type": "object",
        "properties": {"project_id": {"type": "string"}},
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=git_status_tool,
    ),
    ToolDefinition(
      name="GIT_DIFF",
      description=PLATFORM_TOOL_DESCRIPTIONS["GIT_DIFF"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "staged": {"type": "boolean"},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=git_diff_tool,
    ),
    ToolDefinition(
      name="GIT_COMMIT",
      description=PLATFORM_TOOL_DESCRIPTIONS["GIT_COMMIT"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "message": {"type": "string"},
          "approved": {"type": "boolean"},
        },
        "required": ["project_id", "message"],
        "additionalProperties": False,
      },
      handler=git_commit_tool,
    ),
    ToolDefinition(
      name="RUN_TESTS",
      description=PLATFORM_TOOL_DESCRIPTIONS["RUN_TESTS"],
      parameters={
        "type": "object",
        "properties": {
          "project_id": {"type": "string"},
          "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
        },
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=run_tests_tool,
    ),
    ToolDefinition(
      name="RUN_LINT",
      description=PLATFORM_TOOL_DESCRIPTIONS["RUN_LINT"],
      parameters={
        "type": "object",
        "properties": {"project_id": {"type": "string"}},
        "required": ["project_id"],
        "additionalProperties": False,
      },
      handler=run_lint_tool,
    ),
  ]
  return {tool.name: tool for tool in tools}


def codex_tool_registry() -> dict[str, ToolDefinition]:
  merged = dict(website_tool_registry())
  merged.update(platform_tool_registry())
  return merged


def codex_tool_schemas() -> list[dict[str, Any]]:
  return [tool.openai_schema() for tool in codex_tool_registry().values()]


def execute_codex_tool(
  name: str,
  context: ToolRuntimeContext,
  user: UserContext,
  arguments: dict[str, Any],
) -> dict[str, Any]:
  tool = codex_tool_registry().get(name)
  if not tool:
    raise ToolExecutionError(f"Unknown platform tool: {name}")
  if not isinstance(arguments, dict):
    raise ToolExecutionError("Tool arguments must be a JSON object.")
  try:
    from ...platform.policy import classify_tool_risk
  except ImportError:
    try:
      from backend.platform.policy import classify_tool_risk
    except ImportError:
      classify_tool_risk = lambda name, arguments=None: {"risk_tier": "medium", "auto_approve": False, "requires_approval": False, "blocked": False}
  risk = classify_tool_risk(name, arguments=arguments)
  if risk.get("blocked"):
    raise ToolExecutionError(f"Tool {name} is blocked by policy.")
  try:
    result = tool.handler(context, user, arguments)
    if isinstance(result, dict):
      result.setdefault("policy", risk)
    return result
  except (ArtifactValidationError, LocalWorkspaceError, PreviewRuntimeError, StorageError) as exc:
    raise ToolExecutionError(str(exc)) from exc


def website_tool_schemas() -> list[dict[str, Any]]:
  return [tool.openai_schema() for tool in website_tool_registry().values()]


def execute_website_tool(
  name: str,
  context: ToolRuntimeContext,
  user: UserContext,
  arguments: dict[str, Any],
) -> dict[str, Any]:
  tool = website_tool_registry().get(name)
  if not tool:
    raise ToolExecutionError(f"Unknown website tool: {name}")
  if not isinstance(arguments, dict):
    raise ToolExecutionError("Tool arguments must be a JSON object.")
  try:
    return tool.handler(context, user, arguments)
  except (ArtifactValidationError, LocalWorkspaceError, PreviewRuntimeError, StorageError) as exc:
    raise ToolExecutionError(str(exc)) from exc
