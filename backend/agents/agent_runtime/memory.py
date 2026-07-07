from __future__ import annotations

from typing import Any, Callable

try:
  from ...agent_tools import ToolRuntimeContext
  from ...code_diff import build_project_diff, redact_project_diff_for_audit
except ImportError:
  from agent_tools import ToolRuntimeContext
  from code_diff import build_project_diff, redact_project_diff_for_audit

from .constants import REAL_AGENT_RUNTIME_NAME
from .errors import AgentRuntimeLoopError
from .file_ops import project_files_to_tool_files, unique_paths
from .state import append_step
from .tooling import execute_tool_call
from .values import list_value, object_value, string_list, text_or_default
from ..schema.json_safe import json_dumps_for_persistence


ToolExecutor = Callable[[str, ToolRuntimeContext, Any, dict[str, Any]], dict[str, Any]]
AgentProgressCallback = Callable[..., None]


def persist_memory_checkpoint(
  state: dict[str, Any],
  *,
  tool_context: ToolRuntimeContext,
  user: Any,
  namespace: str,
  key: str,
  kind: str,
  content: Any,
  project_id: str,
) -> None:
  content_text = content if isinstance(content, str) else json_dumps_for_persistence(content, context=f"memory.{namespace}.{key}")
  event = {"namespace": namespace, "key": key, "kind": kind, "content": content_text[:1200]}
  state["persisted_memory_events"].append(event)
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "upsert_memory_item"):
    return
  try:
    store.upsert_memory_item(
      user,
      project_id=project_id,
      namespace=namespace,
      key=key,
      kind=kind,
      content=content_text,
      metadata={"source": REAL_AGENT_RUNTIME_NAME},
    )
  except Exception as exc:
    state["persisted_memory_events"].append({"namespace": namespace, "key": key, "kind": "error", "content": str(exc)[:1200]})

def build_project_state_memory(state: dict[str, Any], *, project_id: str) -> dict[str, Any]:
  generated_website = object_value(state.get("generated_website"))
  update_analysis = object_value(state.get("update_analysis"))
  targeted_update = object_value(state.get("targeted_update"))
  scoped_update = object_value(state.get("scoped_update"))
  dynamic_workflow = object_value(state.get("dynamic_workflow_plan"))
  candidate_files = list_value(state.get("candidate_files"))
  existing_files = list_value(object_value(state.get("read_result")).get("files"))

  diff_summary = object_value(state.get("code_diff_summary"))
  if not diff_summary and candidate_files:
    diff_summary = redact_project_diff_for_audit(build_project_diff(existing_files, candidate_files))

  changed_file_paths = unique_paths(
    string_list(state.get("changed_file_paths"), [])
    or string_list(scoped_update.get("changed_file_paths"), [])
    or string_list(targeted_update.get("changed_file_paths"), [])
    or [
      text_or_default(file_diff.get("path"), "")
      for file_diff in list_value(diff_summary.get("files") or diff_summary.get("diffs"))
      if isinstance(file_diff, dict) and text_or_default(file_diff.get("path"), "")
    ]
  )

  update_strategy = (
    text_or_default(targeted_update.get("kind"), "")
    or text_or_default(scoped_update.get("update_mode"), "")
    or text_or_default(update_analysis.get("execution_strategy"), "")
    or text_or_default(update_analysis.get("update_mode"), "")
    or ("generation" if state.get("operation") == "website_generation" else "website_update")
  )
  agent_path = "generation"
  if targeted_update:
    agent_path = "targeted_update"
  elif scoped_update:
    agent_path = "scoped_update"
  elif dynamic_workflow:
    agent_path = "dynamic_agent_workflow"

  preview_version = object_value(object_value(state.get("preview_result")).get("version"))
  preview = object_value(state.get("preview"))
  visual_qa = object_value(state.get("visual_qa_result"))
  diff_files = list_value(diff_summary.get("files") or diff_summary.get("diffs"))
  requirement_trace = object_value(state.get("conversation_requirement"))

  return {
    "project_id": project_id,
    "operation": text_or_default(state.get("operation"), "website_generation"),
    "agent_path": agent_path,
    "user_request": text_or_default(state.get("prompt"), "")[:1000],
    "title": text_or_default(generated_website.get("title"), ""),
    "update_strategy": update_strategy,
    "request_kind": text_or_default(update_analysis.get("request_kind"), text_or_default(targeted_update.get("kind"), "")),
    "requirement_trace": requirement_trace,
    "selected_files": string_list(requirement_trace.get("selected_files"), []) or string_list(update_analysis.get("candidate_files"), []),
    "rejected_files": string_list(requirement_trace.get("rejected_files"), []),
    "update_mode": text_or_default(update_analysis.get("update_mode"), text_or_default(scoped_update.get("update_mode"), "")),
    "feature_plan": object_value(update_analysis.get("feature_plan")),
    "new_file_requirements": object_value(update_analysis.get("new_file_requirements")),
    "scoped_update_tasks": list_value(update_analysis.get("scoped_update_tasks")),
    "scoped_update_task_results": list_value(state.get("scoped_update_task_results")),
    "changed_file_paths": changed_file_paths,
    "diff": {
      "file_count": int(diff_summary.get("file_count") or len(changed_file_paths)),
      "added": int(diff_summary.get("added") or 0),
      "removed": int(diff_summary.get("removed") or 0),
      "files": [
        {
          "path": text_or_default(file_diff.get("path"), ""),
          "status": text_or_default(file_diff.get("status"), ""),
          "added": int(file_diff.get("added") or 0),
          "removed": int(file_diff.get("removed") or 0),
          "old_hash": text_or_default(file_diff.get("old_hash"), ""),
          "new_hash": text_or_default(file_diff.get("new_hash"), ""),
          "old_size": int(file_diff.get("old_size") or 0),
          "new_size": int(file_diff.get("new_size") or 0),
        }
        for file_diff in diff_files[:20]
        if isinstance(file_diff, dict)
      ],
    },
    "preview": {
      "status": text_or_default(preview.get("status"), text_or_default(preview_version.get("status"), "")),
      "url": text_or_default(preview_version.get("preview_url"), text_or_default(preview.get("url"), "")),
    },
    "visual_qa_status": text_or_default(visual_qa.get("status"), ""),
    "validation_status": text_or_default(object_value(state.get("validation_result")).get("status"), ""),
    "rollback_status": "restored" if state.get("rollback_restored") else "not_required",
    "commit": {
      "committed": bool(state.get("committed")),
      "file_count": len(candidate_files),
    },
  }

def load_project_memory(
  state: dict[str, Any],
  *,
  tool_executor: ToolExecutor,
  tool_context: ToolRuntimeContext,
  user: Any,
  project_id: str,
  progress: AgentProgressCallback | None = None,
) -> dict[str, Any]:
  try:
    memory_result = execute_tool_call(
      state,
      tool_executor=tool_executor,
      tool_context=tool_context,
      user=user,
      agent="Memory Agent",
      name="LOAD_PROJECT_MEMORY",
      arguments={"project_id": project_id, "limit": 12},
    )
  except AgentRuntimeLoopError as exc:
    memory_result = {"project_id": project_id, "memories": [], "memory_count": 0, "error": str(exc)}
    append_step(
      state,
      "Memory Agent",
      "load_project_memory",
      {"project_id": project_id},
      {"status": "skipped", "reason": str(exc)[:1200]},
      tool_calls=["LOAD_PROJECT_MEMORY"],
    )
    return memory_result

  chat_session_id = text_or_default(state.get("chat_session_id"), "") or None
  chat_topic_id = text_or_default(state.get("chat_topic_id"), "") or None
  if chat_session_id:
    try:
      from ..memory.runtime_memory import augment_memory_result_with_unified_context
    except ImportError:
      from agents.memory.runtime_memory import augment_memory_result_with_unified_context
    read_files = object_value(state.get("read_result")).get("files")
    files = project_files_to_tool_files(read_files) if isinstance(read_files, list) else []
    memory_result = augment_memory_result_with_unified_context(
      memory_result,
      store=getattr(tool_context, "store", None),
      user=user,
      project_id=project_id,
      prompt=text_or_default(state.get("prompt"), ""),
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=text_or_default(state.get("project_name"), ""),
      files=files,
      progress=progress,
    )
    unified_context = memory_result.get("unified_context")
    if isinstance(unified_context, str) and unified_context.strip():
      state["unified_memory_context"] = unified_context

  state["loaded_memory"] = memory_result.get("memories", [])
  append_step(
    state,
    "Memory Agent",
    "load_project_memory",
    {"project_id": project_id},
    {"memory_count": memory_result.get("memory_count", 0)},
    tool_calls=["LOAD_PROJECT_MEMORY"],
  )
  return memory_result
