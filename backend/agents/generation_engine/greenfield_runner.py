from __future__ import annotations

import os
from typing import Any, Callable

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

try:
  from ..runtime_config import greenfield_parallel_workers_enabled, parallel_greenfield_generation_enabled
except ImportError:
  try:
    from backend.agents.runtime_config import greenfield_parallel_workers_enabled, parallel_greenfield_generation_enabled
  except ImportError:
    from agents.runtime_config import greenfield_parallel_workers_enabled, parallel_greenfield_generation_enabled

from ..requirement_confirmation.prompts import format_confirmation_brief_for_generation
from ..streaming.file_agent import run_streaming_file_agent
from ..streaming.parallel_file_workers import run_parallel_file_workers
from ..streaming.task_planner import (
  build_greenfield_streaming_prompt,
  is_moderate_greenfield_website_request,
  is_rich_greenfield_website_request,
  plan_greenfield_parallel_tasks,
)
from .validation import build_generation_resume_prompt, validate_generation_deliverable
from .scaffold_persist import ensure_visible_scaffold_in_store, visible_project_files_from_store

ProgressCallback = Callable[..., None]


def _greenfield_max_steps() -> int:
  return int(os.getenv("STREAMING_FILE_AGENT_GREENFIELD_MAX_STEPS", "24"))


def _resume_max_steps() -> int:
  return int(os.getenv("STREAMING_FILE_AGENT_GREENFIELD_RESUME_MAX_STEPS", "32"))


def _inject_vite_scaffold_if_needed(
  *,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  project_name: str,
  emit_progress: ProgressCallback,
) -> list[str]:
  visible_files = ensure_visible_scaffold_in_store(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    project_name=project_name,
    emit_progress=emit_progress,
  )
  scaffold_paths = (
    "package.json",
    "index.html",
    "vite.config.js",
    "tailwind.config.js",
    "postcss.config.js",
    "src/main.jsx",
    "src/index.css",
    "src/App.jsx",
  )
  visible_paths = {str(item.get("path") or "") for item in visible_files if isinstance(item, dict)}
  return [path for path in scaffold_paths if path in visible_paths]


def _finalize_visible_generation_result(
  result: dict[str, Any],
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  project_name: str,
  work_plan: dict[str, Any] | None,
  emit_progress: ProgressCallback,
) -> dict[str, Any]:
  ensure_visible_scaffold_in_store(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    project_name=project_name,
    emit_progress=emit_progress,
  )
  visible_files = visible_project_files_from_store(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
  )
  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in visible_files
    if isinstance(item, dict) and item.get("path")
  }
  try:
    from .app_shell import apply_deterministic_app_shell
  except ImportError:
    from backend.agents.generation_engine.app_shell import apply_deterministic_app_shell
  repaired_map, repaired = apply_deterministic_app_shell(files_map, work_plan=work_plan)
  if repaired:
    try:
      from ...agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from backend.agentic.tools.handlers import upsert_project_files_tool
    upsert_project_files_tool(
      tool_context,
      user,
      {
        "project_id": project_id,
        "files": [{"path": "src/App.jsx", "content": repaired_map["src/App.jsx"]}],
        "reason": "deterministic_app_shell",
      },
    )
    emit_progress(
      "app.shell.synthesized",
      "Repaired App.jsx with deterministic routes",
      status="completed",
      detail={"path": "src/App.jsx"},
    )
    visible_files = visible_project_files_from_store(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
    )

  from ..streaming.file_agent import _build_generated_website

  summary = str((result.get("runtime") or {}).get("output_text") or "Website generation completed.")
  payload = [{"path": str(item["path"]), "content": str(item.get("content") or "")} for item in visible_files if item.get("path")]
  generated_website = _build_generated_website(payload, summary=summary)
  runtime = dict(result.get("runtime") or {})
  runtime["visible_file_count"] = len(payload)
  runtime["visible_files"] = [item["path"] for item in payload]
  result["generated_website"] = generated_website
  result["runtime"] = runtime
  artifact_response = dict(result.get("artifact_response") or {})
  artifact_response["files"] = payload
  artifact_response["changed_paths"] = [item["path"] for item in payload]
  artifact_response["changed_file_paths"] = [item["path"] for item in payload]
  result["artifact_response"] = artifact_response
  return result


def _compose_generation_prompt(
  prompt: str,
  *,
  confirmation_brief: dict[str, Any] | None,
) -> str:
  brief_block = format_confirmation_brief_for_generation(confirmation_brief)
  base = prompt.strip()
  if brief_block and brief_block not in base:
    return f"{brief_block}\n\n{base}".strip()
  return base


def _run_single_greenfield_agent(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  work_plan: dict[str, Any],
  confirmation_brief: dict[str, Any] | None,
  attachments: list[dict[str, Any]] | None,
  chat_session_id: str | None,
  project_name: str,
  patch_action: str | None,
  agent_run_id: str | None,
  max_steps: int,
  resume_attempt: bool = False,
) -> dict[str, Any]:
  generation_prompt = build_greenfield_streaming_prompt(prompt)
  if "Greenfield build blueprint" not in generation_prompt:
    generation_prompt = _compose_generation_prompt(prompt, confirmation_brief=confirmation_brief)

  emit_progress(
    "agent.decision",
    "Greenfield generation using single streaming agent with file blueprint",
    status="completed",
    detail={
      "workflow": "greenfield_single_streaming_agent",
      "planned_tasks": work_plan.get("task_count"),
      "resume_attempt": resume_attempt,
    },
  )
  streaming_result = run_streaming_file_agent(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=generation_prompt,
    intent="website_generation",
    artifact_provider=artifact_provider,
    emit_progress=emit_progress,
    attachments=attachments,
    chat_session_id=chat_session_id,
    project_name=project_name,
    patch_action=patch_action,
    agent_run_id=agent_run_id,
    max_steps=max_steps,
    generation_plan=work_plan,
    confirmation_brief=confirmation_brief,
  )
  runtime = dict(streaming_result.get("runtime") or {})
  runtime.update(
    {
      "engine": "streaming_file_agent",
      "workflow": "greenfield_single_streaming_agent",
      "work_plan": work_plan,
      "parallel_workers_skipped": True,
      "resume_attempt": resume_attempt,
    }
  )
  streaming_result["runtime"] = runtime
  return streaming_result


def run_website_generation(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  attachments: list[dict[str, Any]] | None = None,
  chat_session_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  agent_run_id: str | None = None,
  confirmation_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
  composed_prompt = _compose_generation_prompt(prompt, confirmation_brief=confirmation_brief)
  _inject_vite_scaffold_if_needed(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    project_name=project_name,
    emit_progress=emit_progress,
  )

  work_plan = plan_greenfield_parallel_tasks(composed_prompt)
  rich_greenfield = is_rich_greenfield_website_request(composed_prompt)
  moderate_greenfield = is_moderate_greenfield_website_request(composed_prompt)
  use_parallel = (
    greenfield_parallel_workers_enabled()
    and bool(work_plan.get("use_parallel_workers"))
    and (
      parallel_greenfield_generation_enabled()
      or rich_greenfield
      or moderate_greenfield
    )
  )

  if use_parallel:
    if work_plan.get("greenfield"):
      emit_progress(
        "context.greenfield",
        f"Greenfield project — {work_plan.get('task_count')} parallel agents in {work_plan.get('wave_count')} wave(s)",
        status="completed",
        detail={"greenfield": True, "work_plan": work_plan},
      )
    profile = "rich" if rich_greenfield else "moderate" if moderate_greenfield else "parallel"
    emit_progress(
      "agent.decision",
      "Structured greenfield app request — using bounded parallel file workers",
      status="completed",
      detail={
        "workflow": "parallel_file_workers",
        "planned_tasks": work_plan.get("task_count"),
        "greenfield_profile": profile,
      },
    )
    parallel_result = run_parallel_file_workers(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=composed_prompt,
      intent="website_generation",
      artifact_provider=artifact_provider,
      emit_progress=emit_progress,
      work_plan=work_plan,
      attachments=attachments,
      chat_session_id=chat_session_id,
      project_name=project_name,
      patch_action=patch_action,
      agent_run_id=agent_run_id,
    )
    runtime = dict(parallel_result.get("runtime") or {})
    runtime["orchestrator_plan"] = work_plan
    runtime["workflow"] = "parallel_file_workers"
    parallel_result["runtime"] = runtime
    result = parallel_result
  else:
    result = _run_single_greenfield_agent(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=composed_prompt,
      artifact_provider=artifact_provider,
      emit_progress=emit_progress,
      work_plan=work_plan,
      confirmation_brief=confirmation_brief,
      attachments=attachments,
      chat_session_id=chat_session_id,
      project_name=project_name,
      patch_action=patch_action,
      agent_run_id=agent_run_id,
      max_steps=_greenfield_max_steps(),
    )

  project_files = tool_context.store.list_files(project_id, user)
  validation = validate_generation_deliverable(
    prompt=composed_prompt,
    project_files=project_files,
    work_plan=work_plan,
  )
  if validation.get("complete"):
    runtime = dict(result.get("runtime") or {})
    runtime["generation_validation"] = validation
    result["runtime"] = runtime
    return _finalize_visible_generation_result(
      result,
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      project_name=project_name,
      work_plan=work_plan,
      emit_progress=emit_progress,
    )

  emit_progress(
    "generation.incomplete",
    "Generation produced scaffold-only or partial output — resuming with remaining blueprint files",
    status="running",
    detail=validation,
  )

  if validation.get("can_resume"):
    resume_prompt = build_generation_resume_prompt(composed_prompt, validation)
    resume_result = _run_single_greenfield_agent(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=resume_prompt,
      artifact_provider=artifact_provider,
      emit_progress=emit_progress,
      work_plan=work_plan,
      confirmation_brief=confirmation_brief,
      attachments=attachments,
      chat_session_id=chat_session_id,
      project_name=project_name,
      patch_action=patch_action,
      agent_run_id=agent_run_id,
      max_steps=_resume_max_steps(),
      resume_attempt=True,
    )
    project_files = tool_context.store.list_files(project_id, user)
    revalidation = validate_generation_deliverable(
      prompt=composed_prompt,
      project_files=project_files,
      work_plan=work_plan,
    )
    runtime = dict(resume_result.get("runtime") or {})
    runtime["generation_validation"] = revalidation
    runtime["generation_resumed"] = True
    resume_result["runtime"] = runtime
    if not revalidation.get("complete"):
      emit_progress(
        "generation.incomplete",
        "Generation still incomplete after resume — review missing files in the right panel",
        status="failed",
        detail=revalidation,
      )
    return _finalize_visible_generation_result(
      resume_result,
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      project_name=project_name,
      work_plan=work_plan,
      emit_progress=emit_progress,
    )

  runtime = dict(result.get("runtime") or {})
  runtime["generation_validation"] = validation
  result["runtime"] = runtime
  emit_progress(
    "generation.incomplete",
    "Generation did not meet minimum deliverable requirements",
    status="failed",
    detail=validation,
  )
  return _finalize_visible_generation_result(
    result,
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    project_name=project_name,
    work_plan=work_plan,
    emit_progress=emit_progress,
  )
