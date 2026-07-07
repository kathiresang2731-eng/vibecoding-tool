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
from .project_docs import completed_plan_files, initial_plan_files

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
  try:
    from ..agent_runtime.scaffolding import ensure_vite_scaffold_files
    from ..project_workspace import needs_vite_scaffold_repair
    from ..agentic.tools.handlers import upsert_project_files_tool
  except ImportError:
    try:
      from backend.agents.agent_runtime.scaffolding import ensure_vite_scaffold_files
      from backend.agents.project_workspace import needs_vite_scaffold_repair
      from backend.agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from agents.agent_runtime.scaffolding import ensure_vite_scaffold_files
      from agents.project_workspace import needs_vite_scaffold_repair
      from agentic.tools.handlers import upsert_project_files_tool

  current_files = tool_context.store.list_files(project_id, user)
  if not needs_vite_scaffold_repair(current_files):
    return []

  scaffolded, touched_paths = ensure_vite_scaffold_files(
    current_files,
    title=project_name or "Generated Website",
  )
  if not touched_paths:
    return []

  scaffold_by_path = {item["path"]: item["content"] for item in scaffolded}
  write_payload = [
    {"path": path, "content": scaffold_by_path[path]}
    for path in touched_paths
    if path in scaffold_by_path
  ]
  if not write_payload:
    return []

  upsert_project_files_tool(
    tool_context,
    user,
    {"project_id": project_id, "files": write_payload, "reason": "platform_vite_scaffold"},
  )
  emit_progress(
    "scaffold.injected",
    f"Injected {len(write_payload)} platform Vite scaffold file(s)",
    status="completed",
    detail={"paths": [item["path"] for item in write_payload]},
  )
  return [item["path"] for item in write_payload]


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


def _persist_plan_documents(
  *,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  files: list[dict[str, str]],
  emit_progress: ProgressCallback,
  phase: str,
) -> list[str]:
  if not files:
    return []
  try:
    from ...agentic.tools.handlers import upsert_project_files_tool
  except ImportError:
    from backend.agentic.tools.handlers import upsert_project_files_tool
  upsert_project_files_tool(
    tool_context,
    user,
    {
      "project_id": project_id,
      "files": files,
      "reason": f"greenfield_{phase}_documentation",
      "intent": "website_generation",
    },
  )
  paths = [str(item["path"]) for item in files]
  emit_progress(
    "generation.plan.created" if phase == "initial" else "generation.documentation.completed",
    (
      "Created todo.md with the three-worker project plan"
      if phase == "initial"
      else "Updated todo.md and wrote WEBSITE.md with the verified generation outcome"
    ),
    status="completed",
    detail={"paths": paths, "phase": phase, "files": files},
  )
  return paths


def _finalize_plan_documents(
  *,
  result: dict[str, Any],
  prompt: str,
  work_plan: dict[str, Any],
  validation: dict[str, Any],
  tool_context: Any,
  user: UserContext,
  project_id: str,
  emit_progress: ProgressCallback,
) -> dict[str, Any]:
  runtime = dict(result.get("runtime") or {})
  docs = completed_plan_files(
    prompt=prompt,
    work_plan=work_plan,
    validation=validation,
    runtime=runtime,
  )
  doc_paths = _persist_plan_documents(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    files=docs,
    emit_progress=emit_progress,
    phase="completed",
  )
  runtime["project_documentation"] = {
    "paths": doc_paths,
    "todo_complete": bool(validation.get("complete"))
    and str((runtime.get("final_output") or {}).get("preview_status") or "") == "ready",
  }
  runtime["changed_paths"] = list(dict.fromkeys([*(runtime.get("changed_paths") or []), *doc_paths]))
  result["runtime"] = runtime
  return result


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
  chat_topic_id: str | None,
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
    chat_topic_id=chat_topic_id,
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
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  agent_run_id: str | None = None,
  confirmation_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
  composed_prompt = _compose_generation_prompt(prompt, confirmation_brief=confirmation_brief)
  work_plan = plan_greenfield_parallel_tasks(composed_prompt)
  _persist_plan_documents(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    files=initial_plan_files(prompt=composed_prompt, work_plan=work_plan),
    emit_progress=emit_progress,
    phase="initial",
  )
  _inject_vite_scaffold_if_needed(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    project_name=project_name,
    emit_progress=emit_progress,
  )
  rich_greenfield = is_rich_greenfield_website_request(composed_prompt)
  moderate_greenfield = is_moderate_greenfield_website_request(composed_prompt)
  use_parallel = (
    greenfield_parallel_workers_enabled()
    and bool(work_plan.get("use_parallel_workers"))
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
      chat_topic_id=chat_topic_id,
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
      chat_topic_id=chat_topic_id,
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
    return _finalize_plan_documents(
      result=result,
      prompt=composed_prompt,
      work_plan=work_plan,
      validation=validation,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      emit_progress=emit_progress,
    )

  emit_progress(
    "generation.incomplete",
    "Generation produced scaffold-only or partial output — resuming with remaining blueprint files",
    status="running",
    detail=validation,
  )

  prior_runtime = result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
  prior_repairs = int(prior_runtime.get("repair_iterations") or 0)
  if validation.get("can_resume") and prior_repairs < 1:
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
      chat_topic_id=chat_topic_id,
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
    runtime["repair_iterations"] = prior_repairs + 1
    resume_result["runtime"] = runtime
    if not revalidation.get("complete"):
      emit_progress(
        "generation.incomplete",
        "Generation still incomplete after resume — review missing files in the right panel",
        status="failed",
        detail=revalidation,
      )
    return _finalize_plan_documents(
      result=resume_result,
      prompt=composed_prompt,
      work_plan=work_plan,
      validation=revalidation,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      emit_progress=emit_progress,
    )

  if validation.get("can_resume") and prior_repairs >= 1:
    emit_progress(
      "generation.repair.exhausted",
      "The single repair iteration was already used; reporting the remaining generation issues to the user",
      status="failed",
      detail={"repair_iterations": prior_repairs, **validation},
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
  return _finalize_plan_documents(
    result=result,
    prompt=composed_prompt,
    work_plan=work_plan,
    validation=validation,
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    emit_progress=emit_progress,
  )
