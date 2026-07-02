from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

try:
  from ...storage import UserContext
  from ...runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context
except ImportError:
  from storage import UserContext
  from runtime_control import raise_if_runtime_cancelled, submit_with_runtime_context

try:
  from ..agent_tool_catalog import SPECIALIST_AGENT_POLICIES
except ImportError:
  from agents.agent_tool_catalog import SPECIALIST_AGENT_POLICIES

try:
  from ..runtime_config import (
    greenfield_parallel_workers_enabled,
    parallel_file_workers_enabled,
    parallel_greenfield_generation_enabled,
  )
except ImportError:
  from agents.runtime_config import (
    greenfield_parallel_workers_enabled,
    parallel_file_workers_enabled,
    parallel_greenfield_generation_enabled,
  )

try:
  from ..budget_config import AGENT_BUDGETS
except ImportError:
  from agents.budget_config import AGENT_BUDGETS

from .file_agent import run_streaming_file_agent
from .parallel_file_workers import _clone_artifact_provider, run_parallel_file_workers
from .task_planner import (
  build_greenfield_streaming_prompt,
  is_moderate_greenfield_website_request,
  is_requirement_rebuild_request,
  is_rich_greenfield_website_request,
  plan_file_work,
  plan_greenfield_parallel_tasks,
)
from .update_clarification import check_streaming_update_clarification
from .update_preflight import parallel_update_preflight_active, run_parallel_update_preflight
from .streaming_parity import clarification_stream_result, try_deterministic_scoped_patch_streaming, try_deterministic_undefined_reference_fix_streaming

try:
  from ..chat_history import has_prior_chat_messages
except ImportError:
  from agents.chat_history import has_prior_chat_messages

ProgressCallback = Callable[..., None]


def _generation_parallel_workers_enabled(*, intent: str) -> bool:
  if intent == "website_generation":
    return greenfield_parallel_workers_enabled()
  return parallel_file_workers_enabled()


def _has_prior_chat_context(
  tool_context: Any,
  user: Any,
  *,
  project_id: str,
  chat_session_id: str | None,
) -> bool:
  if tool_context is None or user is None or not chat_session_id:
    return False
  store = getattr(tool_context, "store", None)
  if store is None or not hasattr(store, "list_project_chat_messages"):
    return False
  try:
    messages = store.list_project_chat_messages(
      project_id,
      user,
      limit=8,
      chat_session_id=chat_session_id,
    )
    return has_prior_chat_messages(messages, min_messages=1)
  except Exception:
    return False


def _clarification_stream_result(question: str) -> dict[str, Any]:
  return clarification_stream_result(question)


SPECIALIST_AGENTS = ("content", "layout")


def _prompt_tokens(prompt: str) -> set[str]:
  return set(re.findall(r"[a-z0-9]+", prompt.lower()))


def plan_agents_for_request(prompt: str, *, intent: str, skip_specialists: bool = False) -> dict[str, Any]:
  if skip_specialists or intent in {"website_generation", "website_update"}:
    return {
      "agents": ["code"],
      "specialists": [],
      "parallel_groups": [],
      "code_agent": "streaming_file_agent",
      "planning_source": "deterministic_orchestrator",
      "specialists_skipped": True,
    }

  tokens = _prompt_tokens(prompt)
  specialists: list[str] = []

  content_signals = {"copy", "content", "blog", "marketing", "seo", "headline", "about", "story"}
  layout_signals = {"layout", "design", "ux", "responsive", "page", "section", "hero", "footer", "header"}

  if tokens & content_signals or len(prompt) > 180:
    specialists.append("content")
  if tokens & layout_signals or intent == "website_generation":
    specialists.append("layout")

  specialists = [name for name in SPECIALIST_AGENTS if name in specialists]
  if not specialists and intent in {"website_generation", "website_update"}:
    specialists = ["layout"]

  parallel_groups: list[list[str]] = []
  if len(specialists) > 1:
    parallel_groups = [list(specialists)]
  elif specialists:
    parallel_groups = [[specialists[0]]]

  return {
    "agents": [*specialists, "code"],
    "specialists": specialists,
    "parallel_groups": parallel_groups,
    "code_agent": "streaming_file_agent",
    "planning_source": "deterministic_orchestrator",
    "specialists_skipped": False,
  }


def _run_specialist(
  name: str,
  *,
  prompt: str,
  intent: str,
  artifact_provider: Any,
) -> dict[str, Any]:
  policy = SPECIALIST_AGENT_POLICIES.get(name, {})
  role = str(policy.get("role") or name)
  goal = str(policy.get("goal") or "Produce a concise JSON plan for the streaming file agent.")
  json_shape = {
    "content": "summary (string), sections (array of {name, purpose, bullets}), tone (string)",
    "layout": "summary (string), pages (array of paths), components (array of names), grid_notes (string)",
  }[name]
  instructions = (
    f"You are the {policy.get('name', name.title())} ({role}). Goal: {goal} "
    f"Return strict JSON only with keys: {json_shape}."
  )
  user_prompt = (
    f"Intent: {intent}\n"
    f"User request:\n{prompt}\n\n"
    "Keep the plan concise and directly useful for implementation."
  )
  try:
    payload = artifact_provider.generate_json(
      user_prompt,
      system_instruction=instructions,
      trace_label=f"parallel_specialist_{name}",
      max_output_tokens=AGENT_BUDGETS.specialist_output_tokens,
    )
    if isinstance(payload, dict):
      return {"agent": name, "status": "completed", "output": payload}
  except Exception as exc:
    raise_if_runtime_cancelled()
    return {"agent": name, "status": "failed", "error": str(exc), "output": {}}
  return {"agent": name, "status": "failed", "error": "Invalid specialist response", "output": {}}


def _run_specialists_parallel(
  specialist_names: list[str],
  *,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit: ProgressCallback,
  timeout_seconds: int = 90,
) -> list[dict[str, Any]]:
  if not specialist_names:
    return []
  emit(
    "agent.parallel.started",
    f"Running {len(specialist_names)} specialist agent(s) in parallel",
    detail={"agents": specialist_names, "parallel": True},
  )
  results: list[dict[str, Any]] = []
  with ThreadPoolExecutor(max_workers=min(4, len(specialist_names)), thread_name_prefix="worktual-specialist") as pool:
    futures = {
      submit_with_runtime_context(
        pool,
        _run_specialist,
        name,
        prompt=prompt,
        intent=intent,
        artifact_provider=_clone_artifact_provider(artifact_provider),
      ): name
      for name in specialist_names
    }
    for future in futures:
      name = futures[future]
      try:
        result = future.result(timeout=timeout_seconds)
      except Exception as exc:
        result = {"agent": name, "status": "failed", "error": str(exc), "output": {}}
      results.append(result)
      emit(
        f"agent.specialist.{name}",
        f"{name.title()} agent finished",
        status="completed" if result.get("status") == "completed" else "failed",
        detail=result,
      )
  emit(
    "agent.parallel.completed",
    "Parallel specialist planning finished",
    status="completed",
    detail={"agents": specialist_names, "results": results},
  )
  return results


def _format_specialist_context(results: list[dict[str, Any]]) -> str:
  blocks: list[str] = []
  for result in results:
    if result.get("status") != "completed":
      continue
    agent = str(result.get("agent") or "specialist")
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    blocks.append(f"### {agent.title()} agent plan\n```json\n{json.dumps(output, indent=2)}\n```")
  return "\n\n".join(blocks)


def run_parallel_stream_orchestrator(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  skip_specialists: bool = False,
  attachments: list[dict[str, Any]] | None = None,
  chat_session_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  agent_run_id: str | None = None,
) -> dict[str, Any]:
  try:
    from ..prompt_context import current_user_prompt
  except ImportError:
    from agents.prompt_context import current_user_prompt

  prompt = current_user_prompt(prompt)
  if intent == "website_update" and chat_session_id:
    try:
      from .file_agent import _merge_prompt_with_chat_continuity
    except ImportError:
      from agents.streaming.file_agent import _merge_prompt_with_chat_continuity
    prompt = _merge_prompt_with_chat_continuity(
      prompt,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      chat_session_id=chat_session_id,
    )

  def emit(step: str, message: str, **kwargs: Any) -> None:
    emit_progress(step, message, **kwargs)

  project_files = tool_context.store.list_files(project_id, user)
  try:
    from ..project_workspace import is_greenfield_generation
  except ImportError:
    from agents.project_workspace import is_greenfield_generation
  if intent == "website_update" and is_requirement_rebuild_request(prompt):
    emit(
      "routing.coerced",
      "Broad requirement rebuild requested — using website generation instead of a scoped update",
      status="completed",
      detail={"original_intent": "website_update", "coerced_intent": "website_generation"},
    )
    intent = "website_generation"
  if intent == "website_update" and is_greenfield_generation(intent="website_generation", files=project_files):
    emit(
      "routing.coerced",
      "Greenfield project — using website generation instead of update",
      status="completed",
      detail={"original_intent": "website_update", "coerced_intent": "website_generation"},
    )
    intent = "website_generation"

  update_analysis: dict[str, Any] | None = None
  if parallel_update_preflight_active(intent=intent):
    emit(
      "update.analysis.started",
      "Running scoped update analysis before parallel workers",
      status="running",
      detail={"workflow": "parallel_update_preflight"},
    )
    preflight = run_parallel_update_preflight(
      prompt=prompt,
      project_files=project_files,
      control_provider=artifact_provider,
      store=tool_context.store if tool_context is not None else None,
      user=user,
      project_id=project_id,
      chat_session_id=chat_session_id,
      project_name=project_name,
    )
    update_analysis = preflight.get("update_analysis") if isinstance(preflight.get("update_analysis"), dict) else None
    emit(
      "update.analysis.completed",
      "Update analysis ready for parallel worker planning",
      status="completed",
      detail={
        "preflight_source": preflight.get("preflight_source"),
        "update_mode": (update_analysis or {}).get("update_mode"),
        "candidate_files": (update_analysis or {}).get("candidate_files"),
        "task_count": len(list((update_analysis or {}).get("scoped_update_tasks") or [])),
        "memory_items_loaded": preflight.get("memory_items_loaded"),
        "llm_analysis_used": preflight.get("llm_analysis_used"),
        "llm_timeout_seconds": preflight.get("llm_timeout_seconds"),
      },
    )
    if isinstance(update_analysis, dict) and update_analysis.get("update_mode") == "needs_clarification":
      question = str(
        update_analysis.get("clarification_question")
        or "Please specify which page, component, or file to update and what should change."
      )
      emit(
        "update.clarification.required",
        question,
        status="completed",
        detail={"question": question, "workflow": "update_preflight"},
      )
      return _clarification_stream_result(question)

    scoped_result = try_deterministic_undefined_reference_fix_streaming(
      prompt=prompt,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      intent=intent,
      artifact_provider=artifact_provider,
      emit_progress=emit,
      update_analysis=update_analysis,
      patch_action=patch_action,
      chat_session_id=chat_session_id,
      project_name=project_name,
    )
    if scoped_result is not None:
      return scoped_result

    scoped_result = try_deterministic_scoped_patch_streaming(
      update_analysis=update_analysis,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      prompt=prompt,
      intent=intent,
      artifact_provider=artifact_provider,
      emit_progress=emit,
      patch_action=patch_action,
      chat_session_id=chat_session_id,
      project_name=project_name,
    )
    if scoped_result is not None:
      return scoped_result

  work_plan = plan_file_work(prompt, intent=intent, project_files=project_files, update_analysis=update_analysis)

  if intent == "website_update" and isinstance(update_analysis, dict):
    mode = str(update_analysis.get("update_mode") or "")
    candidates = list(update_analysis.get("candidate_files") or [])
    if mode in {"bug_fix", "targeted_patch", "feature_patch"} and len(candidates) <= 2:
      work_plan["use_parallel_workers"] = False
      tasks = list(work_plan.get("tasks") or [])
      if len(tasks) > 1 and not work_plan.get("greenfield"):
        work_plan["tasks"] = tasks[:1]
        work_plan["task_count"] = 1
        work_plan["waves"] = [[tasks[0]["id"]]] if tasks else []
        work_plan["wave_count"] = 1 if tasks else 0
        work_plan["parallel_waves"] = 0

  if intent == "website_update":
    clarification = check_streaming_update_clarification(
      prompt,
      intent=intent,
      project_files=project_files,
      scoped_targets=list(work_plan.get("scoped_targets") or []),
      has_conversation_context=_has_prior_chat_context(
        tool_context,
        user,
        project_id=project_id,
        chat_session_id=chat_session_id,
      ),
    )
    if clarification:
      emit(
        "update.clarification.required",
        clarification,
        status="completed",
        detail={"question": clarification, "workflow": "update_clarification"},
      )
      return _clarification_stream_result(clarification)

  use_parallel = (
    _generation_parallel_workers_enabled(intent=intent)
    and work_plan.get("task_count", 0) >= 2
    and work_plan.get("use_parallel_workers", True)
  )
  if intent == "website_generation" and not use_parallel and parallel_greenfield_generation_enabled():
    alt_plan = plan_greenfield_parallel_tasks(prompt)
    if (
      alt_plan.get("task_count", 0) >= 2
      and alt_plan.get("use_parallel_workers")
      and _generation_parallel_workers_enabled(intent=intent)
    ):
      work_plan = alt_plan
      use_parallel = True
      emit(
        "agent.decision",
        f"Promoted to parallel greenfield plan: {work_plan.get('task_count')} workers in {work_plan.get('wave_count')} wave(s)",
        status="completed",
        detail={"workflow": "parallel_file_workers", "work_plan": work_plan, "planning_source": "greenfield_parallel_fallback"},
      )
  elif (
    intent == "website_generation"
    and not use_parallel
    and not parallel_greenfield_generation_enabled()
    and is_moderate_greenfield_website_request(prompt)
    and _generation_parallel_workers_enabled(intent=intent)
  ):
    alt_plan = plan_greenfield_parallel_tasks(prompt)
    if alt_plan.get("task_count", 0) >= 2 and alt_plan.get("use_parallel_workers"):
      work_plan = alt_plan
      use_parallel = True
      emit(
        "agent.decision",
        f"Promoted moderate greenfield request to parallel plan: {work_plan.get('task_count')} workers",
        status="completed",
        detail={"workflow": "parallel_file_workers", "work_plan": work_plan, "planning_source": "moderate_greenfield_parallel_fallback"},
      )

  greenfield = bool(work_plan.get("greenfield"))
  rich_greenfield = greenfield and intent == "website_generation" and is_rich_greenfield_website_request(prompt)
  moderate_greenfield = greenfield and intent == "website_generation" and is_moderate_greenfield_website_request(prompt)
  if greenfield and intent == "website_generation" and not parallel_greenfield_generation_enabled() and not (rich_greenfield or moderate_greenfield):
    emit(
      "agent.decision",
      "Greenfield generation using single streaming agent (parallel workers disabled for cost and import safety)",
      status="completed",
      detail={"workflow": "greenfield_single_streaming_agent", "planned_tasks": work_plan.get("task_count")},
    )
    streaming_result = run_streaming_file_agent(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=build_greenfield_streaming_prompt(prompt),
      intent=intent,
      artifact_provider=artifact_provider,
      emit_progress=emit_progress,
      attachments=attachments,
      chat_session_id=chat_session_id,
      project_name=project_name,
      patch_action=patch_action,
      agent_run_id=agent_run_id,
    )
    runtime = dict(streaming_result.get("runtime") or {})
    runtime.update(
      {
        "engine": "streaming_file_agent",
        "workflow": "greenfield_single_streaming_agent",
        "work_plan": work_plan,
        "parallel_workers_skipped": True,
      }
    )
    streaming_result["runtime"] = runtime
    return streaming_result
  if greenfield and intent == "website_generation" and (rich_greenfield or moderate_greenfield) and not parallel_greenfield_generation_enabled():
    emit(
      "agent.decision",
      "Structured greenfield app request — enabling bounded parallel workers despite the default greenfield cost switch",
      status="completed",
      detail={
        "workflow": "parallel_file_workers",
        "planned_tasks": work_plan.get("task_count"),
        "reason": "module-heavy website generation needs file-wise workers to avoid a static/partial page",
        "greenfield_profile": "rich" if rich_greenfield else "moderate",
      },
    )
    if not use_parallel and _generation_parallel_workers_enabled(intent=intent):
      alt_plan = plan_greenfield_parallel_tasks(prompt)
      if alt_plan.get("task_count", 0) >= 2:
        work_plan = alt_plan
        use_parallel = bool(alt_plan.get("use_parallel_workers", True))

  if use_parallel:
    if work_plan.get("greenfield"):
      emit(
        "context.greenfield",
        f"Greenfield project — {work_plan.get('task_count')} parallel agents in {work_plan.get('wave_count')} wave(s)",
        status="completed",
        detail={"greenfield": True, "work_plan": work_plan},
      )
    else:
      meaningful_count = sum(
        1
        for item in project_files
        if isinstance(item, dict) and str(item.get("path") or "").startswith(("src/", "index.html", "package.json"))
      )
      emit(
        "context.analysis",
        f"Analyzed {meaningful_count} project file(s) before parallel generation",
        status="completed",
        detail={"file_count": meaningful_count, "planning_source": work_plan.get("planning_source")},
      )
    emit(
      "agent.decision",
      f"Parallel file workers: {work_plan.get('task_count')} agents in {work_plan.get('wave_count')} wave(s) "
      f"({work_plan.get('parallel_waves', 0)} parallel wave(s))",
      status="completed",
      detail={"workflow": "parallel_file_workers", "work_plan": work_plan},
    )
    parallel_result = run_parallel_file_workers(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=prompt,
      intent=intent,
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
    parallel_result["runtime"] = runtime
    return parallel_result

  plan = plan_agents_for_request(prompt, intent=intent, skip_specialists=skip_specialists or intent == "website_update")
  if plan.get("specialists_skipped"):
    emit(
      "agent.decision",
      "Skipping specialist planning and starting code generation immediately",
      status="completed",
      detail={"intent": intent, "workflow": "parallel_stream_orchestrator", "specialists_skipped": True},
    )
  else:
    emit(
      "plan.created",
      f"Orchestrator selected: {', '.join(plan['agents'])}",
      status="completed",
      detail=plan,
    )
    emit(
      "agent.decision",
      "Parallel stream orchestrator planned the minimum agent set for this request",
      status="completed",
      detail={
        "intent": intent,
        "selected_agents": plan["agents"],
        "parallel_groups": plan["parallel_groups"],
        "workflow": "parallel_stream_orchestrator",
      },
    )

  specialist_results = _run_specialists_parallel(
    list(plan.get("specialists") or []),
    prompt=prompt,
    intent=intent,
    artifact_provider=artifact_provider,
    emit=emit,
  )
  specialist_context = _format_specialist_context(specialist_results)
  augmented_prompt = prompt
  if specialist_context:
    augmented_prompt = (
      f"{prompt}\n\n"
      "## Orchestrator specialist plans (use as guidance, then write files immediately)\n"
      f"{specialist_context}"
    )

  streaming_result = run_streaming_file_agent(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=augmented_prompt,
    intent=intent,
    artifact_provider=artifact_provider,
    emit_progress=emit_progress,
    attachments=attachments,
    chat_session_id=chat_session_id,
    project_name=project_name,
    patch_action=patch_action,
  )

  runtime = dict(streaming_result.get("runtime") or {})
  runtime.update(
    {
      "engine": "parallel_stream_orchestrator",
      "orchestrator_plan": plan,
      "specialist_results": specialist_results,
      "parallel_groups_executed": plan.get("parallel_groups") or [],
    }
  )
  streaming_result["runtime"] = runtime
  return streaming_result
