from __future__ import annotations

from typing import Any

from ....dynamic_agents import build_user_agent_registry, hydrate_registry_from_memories
from ...state import append_step, record_agent_message
from ...targeted_updates import build_project_file_keyword_index
from ...tooling import execute_tool_call
from ...values import object_value
from ...file_ops import project_files_to_tool_files
from ...memory import load_project_memory
from ..context import RuntimeActionContext


def build_project_read_result(ctx: RuntimeActionContext) -> dict[str, Any]:
  read_result = execute_tool_call(
    ctx.state,
    tool_executor=ctx.tool_executor,
    tool_context=ctx.tool_context,
    user=ctx.user,
    agent=ctx.agent,
    name="READ_PROJECT_FILES",
    arguments={"project_id": ctx.project_id},
  )
  file_index = build_project_file_keyword_index(project_files_to_tool_files(read_result.get("files")))
  read_result["file_index"] = file_index
  return read_result


def apply_project_read_result(ctx: RuntimeActionContext, read_result: dict[str, Any]) -> None:
  state = ctx.state
  file_index = read_result.get("file_index") or []
  state["project_file_index"] = file_index
  state["read_result"] = read_result
  local_sync = read_result.get("local_sync") if isinstance(read_result.get("local_sync"), dict) else None
  append_step(
    state,
    ctx.agent,
    "read_project_files",
    {"project_id": ctx.project_id},
    {
      "file_count": read_result.get("file_count", 0),
      "indexed_file_count": len(file_index),
      "source": "linked_local_workspace" if local_sync else "backend_project_store",
      "local_sync": local_sync,
    },
    tool_calls=["READ_PROJECT_FILES"],
  )
  source_note = " from the linked local workspace" if local_sync else ""
  record_agent_message(
    state,
    from_agent=ctx.agent,
    to_agent="Supervisor Agent",
    content=f"Loaded {read_result.get('file_count', 0)} existing project files{source_note}.",
    action=ctx.action,
  )


def build_project_memory_result(ctx: RuntimeActionContext) -> dict[str, Any]:
  return load_project_memory(
    ctx.state,
    tool_executor=ctx.tool_executor,
    tool_context=ctx.tool_context,
    user=ctx.user,
    project_id=ctx.project_id,
    progress=ctx.progress,
  )


def apply_project_memory_result(ctx: RuntimeActionContext, memory_result: dict[str, Any]) -> None:
  state = ctx.state
  state["memory_result"] = memory_result
  store = getattr(ctx.tool_context, "store", None)
  registry = build_user_agent_registry(store, ctx.user)
  hydrated_agent_ids = hydrate_registry_from_memories(memory_result.get("memories"), registry=registry)
  ctx.runtime_objects["dynamic_agent_registry"] = registry
  if hydrated_agent_ids:
    state["dynamic_agent_registry"] = registry.snapshot(agent_ids=hydrated_agent_ids)
    append_step(
      state,
      ctx.agent,
      "hydrate_dynamic_agent_registry",
      {"memory_count": memory_result.get("memory_count", 0)},
      {"hydrated_agent_ids": hydrated_agent_ids},
    )
  record_agent_message(
    state,
    from_agent=ctx.agent,
    to_agent="Supervisor Agent",
    content=f"Loaded {memory_result.get('memory_count', 0)} memory items.",
    action=ctx.action,
  )


def handle_read_project_files(ctx: RuntimeActionContext) -> None:
  apply_project_read_result(ctx, build_project_read_result(ctx))


def handle_load_project_memory(ctx: RuntimeActionContext) -> None:
  apply_project_memory_result(ctx, build_project_memory_result(ctx))


def handle_parallel_project_bootstrap(ctx: RuntimeActionContext) -> None:
  from ...parallel_actions import run_parallel_project_bootstrap

  parallel_result = run_parallel_project_bootstrap(ctx)
  apply_project_read_result(ctx, object_value(parallel_result.get("read_result")))
  apply_project_memory_result(ctx, object_value(parallel_result.get("memory_result")))
  append_step(
    ctx.state,
    ctx.agent,
    "parallel_project_bootstrap",
    {"project_id": ctx.project_id},
    {
      "parallel_execution_engine": parallel_result.get("parallel_execution_engine"),
      "file_count": object_value(parallel_result.get("read_result")).get("file_count", 0),
      "memory_count": object_value(parallel_result.get("memory_result")).get("memory_count", 0),
    },
  )
