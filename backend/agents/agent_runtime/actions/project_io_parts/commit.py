from __future__ import annotations

from typing import Any

from ....agentic_flow import generation_memory_content
from ...constants import REAL_AGENT_RUNTIME_NAME
from ...materialize import all_candidate_files, materialize_candidate_files_incrementally
from ...memory import build_project_state_memory, persist_memory_checkpoint
from ...progress import emit_candidate_code_diff_progress, emit_patch_applied_progress, emit_runtime_progress, sync_generated_website_files_from_candidates
from ...runtime_summary import promote_dynamic_agents
from ....schema.json_safe import json_dumps_for_persistence, sanitize_for_persistence, scrub_runtime_objects_from_state
from ...state import append_step
from ...tooling import execute_tool_call
from ...values import list_value, object_value
from ..context import RuntimeActionContext
from .parts import normalize_preview_candidate_files

try:
  from ....patch_approval import require_patch_approval_before_commit
except ImportError:
  from patch_approval import require_patch_approval_before_commit


def handle_materialize_candidate_files(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  normalize_preview_candidate_files(state, agent=agent)
  state["candidate_files"] = all_candidate_files(state)
  sync_generated_website_files_from_candidates(state)
  materialize_candidate_files_incrementally(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
    agent=agent,
  )
  append_step(
    state,
    agent,
    "materialize_candidate_files",
    {"file_count": len(list_value(state.get("candidate_files")))},
    {
      "files_materialized": bool(state.get("files_materialized")),
      "materialized_file_paths": list_value(state.get("materialized_file_paths")),
      "local_sync": state.get("local_sync"),
    },
    tool_calls=[],
  )


def handle_write_project_files(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  if state.get("files_materialized"):
    emit_runtime_progress(
      progress,
      "files.persisted",
      "Project files are already available in the workspace",
      status="completed",
      detail={"file_count": len(list(state.get("candidate_files") or [])), "skipped": True},
    )
    state["committed"] = True
    return

  candidate_files = list(state.get("candidate_files") or [])
  if require_patch_approval_before_commit(
    state,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    progress=progress,
    patch_action=state.get("patch_action"),
  ):
    return
  emit_candidate_code_diff_progress(
    state,
    progress,
    stage="commit_ready",
    message_prefix="Final code changes ready",
  )
  write_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="WRITE_PROJECT_FILES",
    arguments={"project_id": project_id, "files": candidate_files},
  )
  state["write_result"] = write_result
  state["committed"] = True
  state["local_sync"] = write_result.get("local_sync")
  state["local_sync_error"] = write_result.get("local_sync_error")
  persisted_file_count = int(write_result.get("persisted_file_count") or write_result.get("file_count") or 0)
  persisted_paths = [
    str(path).strip()
    for path in list(write_result.get("paths") or [])
    if str(path).strip()
  ]
  emit_patch_applied_progress(
    state,
    progress,
    file_count=persisted_file_count,
    message_prefix="Committed code changes",
  )
  if write_result.get("local_sync_error"):
    emit_runtime_progress(
      progress,
      "local.sync.failed",
      str(write_result.get("local_sync_error")),
      status="failed",
      detail={
        "error": write_result.get("local_sync_error"),
        "project_saved": True,
        "file_count": persisted_file_count,
        "paths": persisted_paths,
      },
    )
  append_step(
    state,
    agent,
    "commit_staged_project_files",
    {
      "file_count": persisted_file_count,
      "requested_file_count": len(candidate_files),
      "paths": persisted_paths,
    },
    write_result,
    tool_calls=["WRITE_PROJECT_FILES"],
  )


def handle_persist_project_memory(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id

  generated_website = object_value(state.get("generated_website"))
  promote_dynamic_agents(state, tool_context=tool_context, user=user, runtime_objects=ctx.runtime_objects)
  scrub_runtime_objects_from_state(state)
  dynamic_memory = sanitize_for_persistence(
    {
      "workflow": object_value(state.get("dynamic_workflow_plan")),
      "specialist_results": object_value(state.get("dynamic_specialist_results")),
      "registry": object_value(state.get("dynamic_agent_registry")),
      "repair_errors": list_value(state.get("repair_errors")),
    }
  )
  memory_output = {
    "memory_kind": "generation_summary",
    "content": (
      f"{generation_memory_content(generated_website, list(state.get('files') or []))}\n"
      f"Dynamic agent run: {json_dumps_for_persistence(dynamic_memory, context='memory.dynamic_run')[:6000]}"
    ),
  }
  persist_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="PERSIST_PROJECT_MEMORY",
    arguments={
      "project_id": project_id,
      "namespace": "agent",
      "key": "latest_generation_summary",
      "kind": "generation_summary",
      "content": memory_output["content"],
      "metadata": {
        "source": REAL_AGENT_RUNTIME_NAME,
        "preview_status": object_value(state.get("preview")).get("status"),
        "visual_qa_status": object_value(state.get("visual_qa_result")).get("status"),
      },
    },
  )
  state["memory"] = {**memory_output, "persist_result": persist_result}
  state["persisted_memory_events"].append(
    {
      "namespace": "agent",
      "key": "latest_generation_summary",
      "kind": "generation_summary",
      "content": memory_output["content"][:1200],
      "tool_call": "PERSIST_PROJECT_MEMORY",
    }
  )
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_dynamic_agent_registry",
    kind="agent_registry",
    content=object_value(state.get("dynamic_agent_registry")),
    project_id=project_id,
  )
  project_state_memory = sanitize_for_persistence(build_project_state_memory(state, project_id=project_id))
  state["latest_project_state_memory"] = project_state_memory
  persist_memory_checkpoint(
    state,
    tool_context=tool_context,
    user=user,
    namespace="agent",
    key="latest_project_state",
    kind="project_state",
    content=project_state_memory,
    project_id=project_id,
  )
  append_step(state, agent, "persist_project_memory", {"title": generated_website.get("title"), "preview_status": object_value(state.get("preview")).get("status")}, state["memory"], tool_calls=["PERSIST_PROJECT_MEMORY"])
