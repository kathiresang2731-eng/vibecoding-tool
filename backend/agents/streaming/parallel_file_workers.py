from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from typing import Any, Callable

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

try:
  from ...api.run_locks import ProjectGenerationCancelledError, raise_if_project_cancelled
  from ...runtime_control import runtime_cancellation_scope, submit_with_runtime_context
except ImportError:
  try:
    from api.run_locks import ProjectGenerationCancelledError, raise_if_project_cancelled
    from runtime_control import runtime_cancellation_scope, submit_with_runtime_context
  except ImportError:
    from contextlib import nullcontext

    ProjectGenerationCancelledError = RuntimeError  # type: ignore[misc,assignment]

    def raise_if_project_cancelled(_project_id: str) -> None:
      return

    def runtime_cancellation_scope(_check):
      return nullcontext()

    def submit_with_runtime_context(executor, function, /, *args, **kwargs):
      return executor.submit(function, *args, **kwargs)

from .file_agent import run_streaming_file_agent
from .shared_work_memory import SharedWorkMemory
from .task_planner import plan_file_work
from .update_preflight import format_update_analysis_worker_block

try:
  from ..prompting.policies import prompt_policy_block
except ImportError:
  from agents.prompting.policies import prompt_policy_block

try:
  from ..budget_config import AGENT_BUDGETS
except ImportError:
  from agents.budget_config import AGENT_BUDGETS

ProgressCallback = Callable[..., None]


def _load_upsert_project_files_tool():
  try:
    from ...agentic.tools.handlers import upsert_project_files_tool
  except ImportError:
    from agentic.tools.handlers import upsert_project_files_tool
  return upsert_project_files_tool


def _load_pull_linked_workspace_to_store():
  try:
    from ...agentic.tools.handlers import pull_linked_workspace_to_store
  except ImportError:
    from agentic.tools.handlers import pull_linked_workspace_to_store
  return pull_linked_workspace_to_store


def _scaffold_materialization_order(paths: list[str]) -> list[str]:
  priority = {
    "package.json": 0,
    "index.html": 1,
    "vite.config.js": 2,
    "vite.config.mjs": 2,
    "vite.config.ts": 2,
    "tailwind.config.js": 3,
    "postcss.config.js": 4,
    "src/main.jsx": 5,
    "src/main.tsx": 5,
    "src/index.css": 6,
    "src/App.jsx": 7,
    "src/App.tsx": 7,
  }
  return sorted(paths, key=lambda path: (priority.get(path, 99), path))


def _worker_timeout_seconds() -> int:
  return max(30, int(os.getenv("PARALLEL_WORKER_TIMEOUT_SECONDS", "180")))


def _clone_artifact_provider(artifact_provider: Any) -> Any:
  try:
    from ..providers.thread_clone import clone_llm_provider
  except ImportError:
    from agents.providers.thread_clone import clone_llm_provider
  return clone_llm_provider(artifact_provider)


def _load_memory_context_block(
  *,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  prompt: str,
  chat_session_id: str | None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  files: list[dict[str, Any]] | None = None,
  ideology_only: bool = False,
) -> str:
  try:
    try:
      from ..memory.context import build_agent_flow_memory_block, build_unified_memory_context_block
      from ..project_workspace import is_greenfield_codebase
    except ImportError:
      from agents.memory.context import build_agent_flow_memory_block, build_unified_memory_context_block
      from agents.project_workspace import is_greenfield_codebase
  except ImportError:
    return ""
  file_list = list(files or [])
  greenfield = ideology_only or is_greenfield_codebase(file_list)
  try:
    block = build_agent_flow_memory_block(
      tool_context.store,
      user,
      project_id=project_id,
      prompt=prompt,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=project_name,
      files=file_list,
      episodic_limit=4,
      ideology_only=greenfield,
    )
    if block:
      return block
    return build_unified_memory_context_block(
      tool_context.store,
      user,
      project_id=project_id,
      prompt=prompt,
      chat_session_id=chat_session_id,
      chat_topic_id=chat_topic_id,
      project_name=project_name,
      files=file_list,
      episodic_limit=4,
      ideology_only=greenfield,
      include_session_state=True,
      include_episodic=True,
    )
  except Exception:
    return ""


def _worker_inline_chars(*, intent: str = "") -> int:
  if intent == "website_update":
    return AGENT_BUDGETS.update_worker_inline_chars
  return AGENT_BUDGETS.worker_inline_chars


def _files_from_map(files_map: dict[str, str]) -> list[dict[str, Any]]:
  return [{"path": path, "content": content} for path, content in files_map.items()]


def _inject_platform_vite_scaffold(
  *,
  shared_memory: SharedWorkMemory,
  tool_context: Any,
  user: UserContext,
  project_id: str,
  project_name: str,
  emit: ProgressCallback,
) -> tuple[list[str], bool]:
  try:
    from ..agent_runtime.scaffolding import ensure_vite_scaffold_files
  except ImportError:
    from agents.agent_runtime.scaffolding import ensure_vite_scaffold_files
  try:
    from ..project_workspace import needs_vite_scaffold_repair
  except ImportError:
    from agents.project_workspace import needs_vite_scaffold_repair

  current_files = _files_from_map(shared_memory.snapshot_files())
  if not needs_vite_scaffold_repair(current_files):
    return [], True

  scaffolded, touched_paths = ensure_vite_scaffold_files(
    current_files,
    title=project_name or "Generated Website",
  )
  if not touched_paths:
    return [], True

  scaffold_by_path = {item["path"]: item["content"] for item in scaffolded}
  write_payload = [
    {"path": path, "content": scaffold_by_path[path]}
    for path in _scaffold_materialization_order(touched_paths)
    if path in scaffold_by_path
  ]
  for item in write_payload:
    shared_memory.update_file(item["path"], item["content"])

  try:
    upsert_project_files_tool = _load_upsert_project_files_tool()
    upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": write_payload, "reason": "platform_vite_scaffold"},
    )
    emit(
      "scaffold.injected",
      f"Injected {len(write_payload)} platform Vite scaffold file(s)",
      status="completed",
      detail={"paths": [item["path"] for item in write_payload]},
    )
    emit(
      "files.materialized",
      f"Materialized {len(write_payload)} dependency scaffold files",
      status="completed",
      detail={
        "paths": [item["path"] for item in write_payload],
        "files": write_payload,
        "phase": "scaffold",
      },
    )
    return [item["path"] for item in write_payload], True
  except Exception as exc:
    emit(
      "scaffold.inject.failed",
      f"Platform scaffold persist failed — will retry on final save: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": [item["path"] for item in write_payload]},
    )
  return [item["path"] for item in write_payload], False


def _worker_max_steps() -> int:
  return int(os.getenv("PARALLEL_FILE_WORKER_MAX_STEPS", "3"))


def _worker_pool_size(task_count: int) -> int:
  try:
    from ..runtime_config import parallel_file_worker_max
  except ImportError:
    from agents.runtime_config import parallel_file_worker_max
  configured = parallel_file_worker_max()
  cpu_cap = max(4, (os.cpu_count() or 4) + 2)
  return max(1, min(configured, cpu_cap, task_count))


def _worker_max_steps_for_task(task: dict[str, Any]) -> int:
  base = _worker_max_steps()
  kind = str(task.get("kind") or "")
  if kind in {"greenfield_integration_group", "greenfield_page_group", "greenfield_feature_group"}:
    path_count = len([path for path in (task.get("paths") or []) if str(path or "").strip()])
    return int(os.getenv("GREENFIELD_THREE_WORKER_MAX_STEPS", str(max(base, path_count + 3))))
  if kind == "greenfield_app_shell":
    return int(os.getenv("GREENFIELD_APP_SHELL_MAX_STEPS", str(max(base, 4))))
  if kind in {"greenfield_pages", "greenfield_page", "greenfield_components", "greenfield_component", "greenfield_data", "greenfield_data_file", "greenfield_backend"}:
    return int(os.getenv("GREENFIELD_MODULE_MAX_STEPS", str(max(base, 4))))
  scope = str(task.get("scope") or "")
  if scope.startswith("onboarding flow"):
    return int(os.getenv("ONBOARDING_FLOW_MAX_STEPS", str(max(base, 4))))
  return base


def _request_model_call_budget(*, intent: str) -> int:
  try:
    from ..runtime_config import parallel_model_call_budget
  except ImportError:
    from agents.runtime_config import parallel_model_call_budget
  return parallel_model_call_budget(intent=intent)


def _assign_worker_step_budgets(tasks: list[dict[str, Any]], *, intent: str) -> dict[str, int]:
  if not tasks:
    return {}
  remaining_budget = _request_model_call_budget(intent=intent)
  remaining_tasks = len(tasks)
  budgets: dict[str, int] = {}
  for task in tasks:
    task_id = str(task.get("id") or "")
    if not task_id:
      remaining_tasks -= 1
      continue
    if remaining_budget <= 0:
      budgets[task_id] = 0
      remaining_tasks -= 1
      continue
    max_for_task = max(1, _worker_max_steps_for_task(task))
    fair_share = max(1, remaining_budget // max(1, remaining_tasks))
    assigned = max(1, min(max_for_task, fair_share))
    budgets[task_id] = assigned
    remaining_budget = max(0, remaining_budget - assigned)
    remaining_tasks -= 1
  return budgets


def _greenfield_worker_instructions(task: dict[str, Any]) -> str:
  kind = str(task.get("kind") or "")
  if kind == "greenfield_integration_group":
    return (
      "You are the integration worker. Create EVERY assigned shared component and update src/App.jsx. "
      "Use the route contract below as authoritative: import every planned page by its promised default export, "
      "declare a working React Router route for every page, provide a safe fallback route, and make navigation links "
      "match those paths. Keep src/App.jsx thin. Co-worker pages are generated concurrently, so rely on the agreed "
      "contract rather than waiting for their code. Do not edit platform scaffold files outside your allowed paths."
    )
  if kind == "greenfield_page_group":
    return (
      "You are the primary journey worker. Create EVERY assigned page, each with the exact default export promised "
      "by the route contract. Pages must be responsive and standalone, and user actions must navigate to real planned "
      "routes. Do not import co-worker page files. Finish all assigned files before returning."
    )
  if kind == "greenfield_feature_group":
    return (
      "You are the secondary feature/data worker. Create EVERY assigned file. React pages use the exact default "
      "exports in the route contract; data files expose stable named exports; backend files must be runnable and must "
      "not import frontend modules. Do not invent imports to files outside the shared contract."
    )
  if kind == "greenfield_app_shell":
    return (
      "Platform scaffold files already exist. Update only src/App.jsx to import generated pages/components "
      "and declare React Router routes. Import only co-worker outputs that are completed in shared memory; "
      "skip failed or missing planned modules instead of importing them. Do not rewrite package.json, "
      "index.html, vite.config.js, or src/main.jsx."
    )
  if kind in {"greenfield_page", "greenfield_pages"}:
    return (
      "This is wave 1 (single page). Scaffold already exists in shared memory — "
      "build one complete standalone page component for your assigned path only. "
      "Include multiple polished sections (hero with gradient/bg imagery, feature grid, metrics or testimonials, CTA band) "
      "using theme tokens, generous spacing (py-16+, gap-8), rounded-xl cards, shadows, and accessible text contrast. "
      "Wire every button and CTA with real onClick handlers and react-router-dom useNavigate/Link — "
      "never leave decorative or broken handlers. "
      "Do not import relative files from same-wave co-workers; the App shell integrates them later. "
      "Keep the file under 350 lines with balanced braces and export default."
    )
  if kind in {"greenfield_component", "greenfield_components"}:
    return (
      "This is wave 1 (single component). Create one reusable layout/nav/footer/feature component. "
      "Match the export name in your Main Coding Agent contract. "
      "Interactive controls must call real handlers or navigation helpers passed via props. "
      "Do not import page files that may still be generating. "
      "Keep the file under 350 lines with balanced braces and export default."
    )
  if kind in {"greenfield_data_file", "greenfield_data"}:
    return (
      "This is wave 1 (data/theme file). Provide theme tokens or mock data that pages and components can import."
    )
  scope = str(task.get("scope") or "")
  if scope.startswith("onboarding flow"):
    return (
      "Onboarding flow update: add skip/remove modal in YOUR assigned file only. "
      "Do not read or edit other onboarding files — parallel workers handle those."
    )
  return ""


def _format_coordination_contract(
  contract: dict[str, Any] | None,
  *,
  task: dict[str, Any],
) -> str:
  if not isinstance(contract, dict) or not contract:
    return ""
  task_id = str(task.get("id") or "")
  task_contracts = [
    item for item in (contract.get("task_contracts") or [])
    if isinstance(item, dict)
  ]
  own_contract = next((item for item in task_contracts if str(item.get("task_id") or "") == task_id), None)
  lines = [
    "## Main Coding Agent coordination contract",
    f"Website type: {contract.get('website_type') or 'custom'}",
    str(contract.get("main_coding_agent") or "Main Coding Agent owns integration and merge safety."),
  ]
  rules = [str(item) for item in (contract.get("communication_rules") or []) if str(item or "").strip()]
  if rules:
    lines.append("Rules:")
    lines.extend(f"- {rule}" for rule in rules[:8])
  if own_contract:
    allowed = ", ".join(own_contract.get("allowed_paths") or [])
    depends = ", ".join(own_contract.get("depends_on") or []) or "none"
    export_name = own_contract.get("export_name") or "n/a"
    export_type = own_contract.get("export_type") or "n/a"
    lines.extend(
      [
        "",
        "Your contract:",
        f"- Allowed paths: {allowed}",
        f"- Depends on: {depends}",
        f"- Export: {export_type} {export_name}",
        f"- Acceptance: {own_contract.get('acceptance') or 'Write only your assigned file and keep it build-safe.'}",
      ]
    )
    own_exports = own_contract.get("exports") if isinstance(own_contract.get("exports"), dict) else {}
    for path, export in own_exports.items():
      export = export if isinstance(export, dict) else {}
      lines.append(
        f"- `{path}` export: {export.get('export_type') or 'module'} "
        f"{export.get('export_name') or 'n/a'}"
      )
  route_contract = [
    item for item in (contract.get("route_contract") or [])
    if isinstance(item, dict)
  ]
  if route_contract:
    lines.extend(["", "Authoritative route/export map:"])
    for item in route_contract:
      lines.append(
        f"- URL `{item.get('route')}` => `{item.get('file_path')}` default export "
        f"`{item.get('component')}`; App import `{item.get('import_path')}`"
      )
  if task_contracts:
    lines.append("")
    lines.append("Co-worker output map:")
    for item in task_contracts[:16]:
      paths = ", ".join(item.get("allowed_paths") or [])
      exports = item.get("exports") if isinstance(item.get("exports"), dict) else {}
      export_summary = ", ".join(
        f"{path}:{(spec if isinstance(spec, dict) else {}).get('export_name') or 'module'}"
        for path, spec in exports.items()
      )
      if not export_summary:
        export_name = item.get("export_name") or "n/a"
        import_path = item.get("import_path_from_app") or ""
        export_summary = f"{export_name}{f' ({import_path})' if import_path else ''}"
      lines.append(f"- {item.get('task_id')}: {item.get('kind')} -> {paths}; exports {export_summary}")
  failed_deps = [str(item) for item in (task.get("failed_dependencies") or []) if str(item or "").strip()]
  completed_deps = [str(item) for item in (task.get("completed_dependencies") or []) if str(item or "").strip()]
  if completed_deps or failed_deps:
    lines.append("")
    lines.append(f"Dependency status: completed={completed_deps or ['none']}; failed={failed_deps or ['none']}.")
  return "\n".join(lines)


def _build_worker_prompt(
  *,
  user_prompt: str,
  task: dict[str, Any],
  shared_memory: SharedWorkMemory,
  memory_context_block: str = "",
  update_analysis_block: str = "",
  intent: str = "",
  coordination_contract: dict[str, Any] | None = None,
) -> str:
  paths = task.get("paths") or []
  scope = str(task.get("scope") or "").strip()
  memory_block = shared_memory.context_for_task(
    task_id=str(task.get("id") or "worker"),
    depends_on=[str(item) for item in (task.get("depends_on") or [])],
  )
  is_greenfield_task = str(task.get("kind") or "").startswith("greenfield")
  lines: list[str] = []
  if is_greenfield_task:
    summary = scope or user_prompt.strip()[:600]
    if summary:
      lines.append(f"User request summary: {summary}")
  else:
    lines.append(user_prompt.strip())
  lines.extend(
    [
      "",
      "## Parallel worker assignment",
      f"Task id: {task.get('id')}",
      f"Kind: {task.get('kind')}",
      f"Allowed paths (only edit these): {', '.join(paths)}",
    ]
  )
  if scope:
    lines.append(f"Scope: {scope}")
  greenfield_hint = _greenfield_worker_instructions(task)
  if greenfield_hint:
    lines.append(greenfield_hint)
  contract_block = _format_coordination_contract(coordination_contract, task=task)
  if contract_block:
    lines.extend(["", contract_block])
  max_inline = _worker_inline_chars(intent=intent)
  for path in paths:
    content = shared_memory.get_file(path)
    if not content:
      continue
    truncated = len(content) > max_inline
    snippet = content[:max_inline]
    lines.append(
      f"\n### Current `{path}`{' (truncated — use read_file for tail)' if truncated else ''}\n```\n{snippet}\n```"
    )
  lines.append(
    "Co-worker agents are updating other assigned files in parallel. Analyze the snippets above and "
    "apply edits immediately with str_replace on existing files. write_file is only for brand-new paths. "
    "Never replace an entire existing file — the backend blocks large rewrites. "
    "Never delete or prune unmentioned files. Preserve exported names, route ids, prop names, data shapes, "
    "and package dependencies promised in the coordination contract. "
    "If another worker's file is required, explain the missing dependency instead of editing outside your owned paths. "
    "If str_replace fails, re-read the file and use a longer exact old_string. "
    "Only call read_file when you need to verify an exact line range. Do not list or read unrelated project files."
  )
  lines.extend(["", prompt_policy_block(include_generation=True, include_update=intent == "website_update")])
  if memory_block:
    lines.extend(["", memory_block])
  if memory_context_block and not is_greenfield_task:
    lines.extend(["", memory_context_block.strip()])
  if update_analysis_block:
    lines.extend(["", update_analysis_block.strip()])
  return "\n".join(lines)


def _run_single_worker(
  task: dict[str, Any],
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  intent: str,
  user_prompt: str,
  artifact_provider: Any,
  shared_memory: SharedWorkMemory,
  emit_progress: ProgressCallback,
  memory_context_block: str = "",
  update_analysis: dict[str, Any] | None = None,
  coordination_contract: dict[str, Any] | None = None,
  max_steps: int | None = None,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
) -> dict[str, Any]:
  task_id = str(task.get("id") or "worker")
  agent_label = f"File Worker {task_id}"
  allowed_paths = frozenset(str(path) for path in (task.get("paths") or []))

  def file_resolver(path: str) -> str:
    raise_if_project_cancelled(project_id)
    staged = shared_memory.get_file(path)
    if staged:
      return staged
    try:
      from ...agentic.tools.platform import read_file_tool
    except ImportError:
      from agentic.tools.platform import read_file_tool
    payload = read_file_tool(tool_context, user, {"project_id": project_id, "path": path})
    return str(payload.get("content") or "")

  worker_prompt = _build_worker_prompt(
    user_prompt=user_prompt,
    task=task,
    shared_memory=shared_memory,
    memory_context_block=memory_context_block,
    update_analysis_block=format_update_analysis_worker_block(update_analysis, task=task),
    intent=intent,
    coordination_contract=coordination_contract,
  )

  worker_provider = _clone_artifact_provider(artifact_provider)

  def _on_file_staged(path: str, content: str) -> None:
    raise_if_project_cancelled(project_id)
    try:
      from .syntax_guard import guard_syntax_write
    except ImportError:
      from agents.streaming.syntax_guard import guard_syntax_write
    blocked = guard_syntax_write(path, content)
    if blocked:
      worker_emit(
        "gate.syntax.blocked",
        str(blocked.get("error") or "syntax blocked"),
        status="failed",
        detail=blocked,
      )
      raise ValueError(str(blocked.get("error") or "syntax blocked"))
    shared_memory.update_file(path, content)
    shared_memory.publish_staged(
      task_id=task_id,
      agent_label=agent_label,
      path=path,
      note=f"{agent_label} staged changes in {path}",
    )
    worker_emit(
      "files.materialized",
      f"Materialized {path}",
      status="completed",
      detail={
        "paths": [path],
        "files": [{"path": path, "content": content}],
        "phase": "parallel_worker",
        "parallel_worker": task_id,
        "agent": agent_label,
      },
    )
    worker_emit(
      "agent.a2a.broadcast",
      f"{agent_label} staged {path} for co-workers",
      status="running",
      detail={
        "from_task": task_id,
        "from_agent": agent_label,
        "path": path,
        "protocol": "worktual-parallel-a2a-v1",
      },
    )

  def worker_emit(step: str, message: str, **kwargs: Any) -> None:
    detail = kwargs.get("detail") if isinstance(kwargs.get("detail"), dict) else {}
    merged = {**(detail or {}), "parallel_worker": task_id, "agent": agent_label}
    emit_progress(step, message, detail=merged, status=kwargs.get("status", "running"))

  emit_progress(
    "agent.worker.started",
    f"{agent_label} started",
    status="running",
    detail={"task": task, "paths": list(allowed_paths)},
  )

  try:
    with runtime_cancellation_scope(lambda: raise_if_project_cancelled(project_id)):
      raise_if_project_cancelled(project_id)
      result = run_streaming_file_agent(
        project_id=project_id,
        user=user,
        tool_context=tool_context,
        prompt=worker_prompt,
        intent=intent,
        artifact_provider=worker_provider,
        emit_progress=worker_emit,
        max_steps=max(1, int(max_steps or _worker_max_steps_for_task(task))),
        allowed_write_paths=allowed_paths,
        persist_to_store=False,
        skip_workspace_pull=True,
        file_resolver_override=file_resolver,
        on_file_staged=_on_file_staged,
        worker_id=task_id,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
      )
      raise_if_project_cancelled(project_id)
    status = "completed" if result.get("runtime", {}).get("changed_paths") else "partial"
    shared_memory.publish_completion(
      task_id=task_id,
      agent_label=agent_label,
      paths=sorted(result.get("runtime", {}).get("changed_paths") or []),
      summary=str(result.get("runtime", {}).get("output_text") or "Updated assigned files.")[:1200],
      status=status,
    )
    a2a_message = shared_memory.messages[-1] if shared_memory.messages else {}
    if a2a_message:
      worker_emit(
        "agent.a2a.message",
        f"{agent_label} → orchestrator",
        status="completed",
        detail=a2a_message,
      )
    emit_progress(
      "agent.worker.completed",
      f"{agent_label} finished",
      status="completed",
      detail={"task_id": task_id, "status": status, "paths": result.get("runtime", {}).get("changed_paths")},
    )
    return {"task_id": task_id, "status": status, "result": result}
  except Exception as exc:
    shared_memory.publish_completion(
      task_id=task_id,
      agent_label=agent_label,
      paths=[],
      summary=str(exc)[:500],
      status="failed",
    )
    emit_progress(
      "agent.worker.failed",
      f"{agent_label} failed: {exc}",
      status="failed",
      detail={"task_id": task_id, "error": str(exc)},
    )
    return {"task_id": task_id, "status": "failed", "error": str(exc)}


def _wave_changed_paths(
  wave_results: list[dict[str, Any]],
  *,
  files_before: dict[str, str],
  staged: dict[str, str],
) -> list[str]:
  paths: set[str] = set()
  for item in wave_results:
    runtime = (item.get("result") or {}).get("runtime") or {}
    for path in runtime.get("changed_paths") or []:
      paths.add(str(path))
  for path, content in staged.items():
    if files_before.get(path, "") != content:
      paths.add(path)
  return sorted(paths)


def _run_wave_syntax_checkpoint(
  *,
  changed_paths: list[str],
  staged: dict[str, str],
  emit: ProgressCallback,
) -> list[str]:
  if not changed_paths:
    return []
  try:
    from .file_agent import _diagnose_changed_source_files
  except ImportError:
    from agents.streaming.file_agent import _diagnose_changed_source_files
  files = [{"path": path, "content": staged[path]} for path in changed_paths if path in staged]
  issues = _diagnose_changed_source_files(files)
  if issues:
    emit(
      "gate.syntax.wave",
      f"Syntax scan found {len(issues)} issue(s) after wave — next workers should avoid repeating these",
      status="failed",
      detail={"issues": issues[:8]},
    )
  else:
    emit(
      "gate.syntax.wave",
      f"Syntax scan passed for {len(changed_paths)} file(s) in this wave",
      status="completed",
      detail={"changed_paths": changed_paths},
    )
  return issues


def _emit_wave_orchestration_checkpoint(
  *,
  wave_index: int,
  wave_count: int,
  wave_results: list[dict[str, Any]],
  shared_memory: SharedWorkMemory,
  work_plan: dict[str, Any],
  syntax_issues: list[str],
  emit: ProgressCallback,
) -> None:
  summaries = [
    f"{item.get('task_id')}: {item.get('status')}"
    for item in wave_results
  ]
  failed = [item for item in wave_results if item.get("status") == "failed"]
  instruction = (
    f"Wave {wave_index}/{wave_count} complete ({'; '.join(summaries)}). "
  )
  if wave_index < wave_count:
    instruction += (
      "Next-wave workers: use shared agent memory exports, write only your assigned paths, "
      "and import symbols announced by prior workers."
    )
  else:
    instruction += "All waves complete — merging files and running build gate."
  if syntax_issues:
    instruction += f" Fix these syntax issues if touching affected files: {'; '.join(syntax_issues[:4])}."

  orch_msg = {
    "sequence": len(shared_memory.messages) + 1,
    "from_agent": "Parallel Orchestrator",
    "to_agent": "next-wave-workers" if wave_index < wave_count else "build-gate",
    "from_task": "orchestrator",
    "status": "failed" if failed else "completed",
    "wave": wave_index,
    "wave_count": wave_count,
    "paths_changed": [],
    "summary": instruction[:1200],
    "greenfield": bool(work_plan.get("greenfield")),
    "protocol": "worktual-orchestrator-a2a-v1",
  }
  shared_memory.messages.append(orch_msg)
  emit(
    "orchestrator.wave.checkpoint",
    f"Wave {wave_index} orchestration: coordinating {'next agents' if wave_index < wave_count else 'build verification'}",
    status="failed" if failed else "completed",
    detail={"a2a": orch_msg, "wave_results": summaries, "syntax_issues": syntax_issues[:6]},
  )


def _seed_coordination_contract(
  *,
  shared_memory: SharedWorkMemory,
  work_plan: dict[str, Any],
  emit: ProgressCallback,
) -> None:
  contract = work_plan.get("coordination_contract")
  if not isinstance(contract, dict) or not contract:
    return
  task_contracts = [
    item for item in (contract.get("task_contracts") or [])
    if isinstance(item, dict)
  ]
  summary = (
    f"Main Coding Agent assigned {len(task_contracts)} co-worker contracts for "
    f"{contract.get('website_type') or 'custom'} generation. "
    "Co-workers must write only assigned paths, publish exports, and let the App shell integrate completed outputs."
  )
  message = {
    "sequence": len(shared_memory.messages) + 1,
    "from_task": "main-coding-agent",
    "from_agent": "Main Coding Agent",
    "to_agent": "co-workers",
    "status": "completed",
    "paths_changed": [],
    "summary": summary[:1200],
    "contracts": task_contracts,
    "protocol": "worktual-parallel-a2a-v1",
  }
  shared_memory.messages.append(message)
  emit(
    "agent.parallel.contract",
    "Main Coding Agent published file ownership and import contracts",
    status="completed",
    detail={
      "website_type": contract.get("website_type"),
      "task_count": len(task_contracts),
      "protocol": contract.get("worker_protocol"),
      "contracts": task_contracts,
    },
  )


def _persist_wave_intermediate(
  *,
  changed_paths: list[str],
  staged: dict[str, str],
  tool_context: Any,
  user: UserContext,
  project_id: str,
  emit: ProgressCallback,
  wave_index: int,
) -> None:
  if not changed_paths:
    return
  try:
    upsert_project_files_tool = _load_upsert_project_files_tool()
    payload = [{"path": path, "content": staged[path]} for path in changed_paths if path in staged]
    if not payload:
      return
    upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": payload, "reason": f"parallel_wave_{wave_index}_checkpoint"},
    )
    emit(
      "files.wave.persisted",
      f"Wave {wave_index}: saved {len(payload)} intermediate file(s) for downstream agents",
      status="completed",
      detail={"paths": [item["path"] for item in payload], "wave": wave_index},
    )
    return [item["path"] for item in payload]
  except Exception as exc:
    emit(
      "files.wave.persist.failed",
      f"Wave {wave_index} intermediate persist skipped: {exc}",
      status="failed",
      detail={"wave": wave_index, "error": str(exc)},
    )
  return []


def run_parallel_file_workers(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  work_plan: dict[str, Any] | None = None,
  attachments: list[dict[str, Any]] | None = None,
  chat_session_id: str | None = None,
  chat_topic_id: str | None = None,
  project_name: str = "",
  patch_action: str | None = None,
  agent_run_id: str | None = None,
) -> dict[str, Any]:
  def emit(step: str, message: str, **kwargs: Any) -> None:
    emit_progress(step, message, **kwargs)

  if not work_plan:
    project_files = tool_context.store.list_files(project_id, user)
    work_plan = plan_file_work(
      prompt,
      intent=intent,
      project_files=project_files,
      artifact_provider=artifact_provider,
    )

  tasks = list(work_plan.get("tasks") or [])
  waves = list(work_plan.get("waves") or [])
  if len(tasks) < 2:
    raise ValueError("Parallel file workers require at least two tasks.")
  worker_step_budgets = _assign_worker_step_budgets(tasks, intent=intent)

  emit(
    "agent.parallel.plan",
    f"Split work into {len(tasks)} task(s) across {len(waves)} wave(s)",
    status="completed",
    detail={
      **work_plan,
      "model_call_budget": _request_model_call_budget(intent=intent),
      "worker_step_budgets": worker_step_budgets,
    },
  )

  try:
    pull_linked_workspace_to_store = _load_pull_linked_workspace_to_store()
    upsert_project_files_tool = _load_upsert_project_files_tool()
  except ImportError as exc:
    raise ValueError(f"Project file tools unavailable: {exc}") from exc

  pull_linked_workspace_to_store(tool_context, user, project_id=project_id, source="parallel_file_workers")

  files_map = {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in tool_context.store.list_files(project_id, user)
    if isinstance(item, dict) and item.get("path")
  }
  shared_memory = SharedWorkMemory(project_id=project_id, files=dict(files_map))
  _seed_coordination_contract(shared_memory=shared_memory, work_plan=work_plan, emit=emit)
  if intent in {"website_generation", "website_update"}:
    scaffold_paths, scaffold_persisted = _inject_platform_vite_scaffold(
      shared_memory=shared_memory,
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      project_name=project_name,
      emit=emit,
    )
    if scaffold_persisted and scaffold_paths:
      files_map.update(
        {path: shared_memory.get_file(path) or "" for path in scaffold_paths if shared_memory.get_file(path)}
      )
  task_by_id = {str(task["id"]): task for task in tasks}
  worker_results: list[dict[str, Any]] = []
  all_tool_calls: list[dict[str, Any]] = []
  greenfield = bool(work_plan.get("greenfield"))
  update_analysis = work_plan.get("update_analysis") if isinstance(work_plan.get("update_analysis"), dict) else None
  worker_timeout = _worker_timeout_seconds()

  for wave_index, wave in enumerate(waves, start=1):
    raise_if_project_cancelled(project_id)
    completed_task_ids = {
      str(item.get("task_id") or "")
      for item in worker_results
      if item.get("status") in {"completed", "partial"}
    }
    failed_task_ids = {
      str(item.get("task_id") or "")
      for item in worker_results
      if item.get("status") == "failed"
    }
    wave_tasks = []
    for task_id in wave:
      if task_id not in task_by_id:
        continue
      task = dict(task_by_id[task_id])
      depends_on = [str(item) for item in (task.get("depends_on") or [])]
      task["completed_dependencies"] = [item for item in depends_on if item in completed_task_ids]
      task["failed_dependencies"] = [item for item in depends_on if item in failed_task_ids]
      wave_tasks.append(task)
    skipped_budget_tasks = [
      task for task in wave_tasks if worker_step_budgets.get(str(task.get("id") or ""), 0) <= 0
    ]
    wave_tasks = [
      task for task in wave_tasks if worker_step_budgets.get(str(task.get("id") or ""), 0) > 0
    ]
    for task in skipped_budget_tasks:
      task_id = str(task.get("id") or "")
      shared_memory.publish_completion(
        task_id=task_id,
        agent_label=f"File Worker {task_id}",
        paths=[],
        summary="Skipped because the request-level model-call budget was already allocated.",
        status="skipped",
      )
      worker_results.append(
        {
          "task_id": task_id,
          "status": "skipped",
          "error": "Request-level model-call budget exhausted before this worker.",
        }
      )
      emit(
        "agent.worker.skipped",
        f"File Worker {task_id} skipped by model-call budget",
        status="completed",
        detail={"task_id": task_id, "model_call_budget": _request_model_call_budget(intent=intent)},
      )
    if not wave_tasks:
      continue
    staged_snapshot = shared_memory.snapshot_files()
    memory_context_block = ""
    if not greenfield:
      memory_context_block = _load_memory_context_block(
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        prompt=prompt,
        chat_session_id=chat_session_id,
        chat_topic_id=chat_topic_id,
        project_name=project_name,
        files=_files_from_map(staged_snapshot),
        ideology_only=greenfield and wave_index == 1,
      )
    if memory_context_block:
      emit(
        "memory.context.injected",
        "Injected agent-flow memory (session, episodic, chat continuity) into parallel worker wave",
        status="completed",
        detail={
          "wave": wave_index,
          "chat_session_id": chat_session_id,
          "chat_topic_id": chat_topic_id,
          "context_chars": len(memory_context_block),
          "includes_chat_continuity": "CONVERSATION CONTINUITY" in memory_context_block,
        },
      )
    emit(
      "agent.parallel.wave.started",
      f"Wave {wave_index}/{len(waves)}: {len(wave_tasks)} worker(s) in parallel",
      status="running",
      detail={"wave": wave_index, "task_ids": [task["id"] for task in wave_tasks]},
    )
    wave_results: list[dict[str, Any]] = []
    worker_kwargs = {
      "project_id": project_id,
      "user": user,
      "tool_context": tool_context,
      "intent": intent,
      "user_prompt": prompt,
      "artifact_provider": artifact_provider,
      "shared_memory": shared_memory,
      "emit_progress": emit_progress,
      "memory_context_block": memory_context_block,
      "update_analysis": update_analysis,
      "coordination_contract": work_plan.get("coordination_contract") if isinstance(work_plan.get("coordination_contract"), dict) else None,
      "chat_session_id": chat_session_id,
      "chat_topic_id": chat_topic_id,
    }
    if len(wave_tasks) == 1:
      task_id = str(wave_tasks[0].get("id") or "")
      wave_results.append(_run_single_worker(wave_tasks[0], **worker_kwargs, max_steps=worker_step_budgets.get(task_id)))
    else:
      with ThreadPoolExecutor(
        max_workers=_worker_pool_size(len(wave_tasks)),
        thread_name_prefix="worktual-file-worker",
      ) as pool:
        futures = {
          submit_with_runtime_context(
            pool,
            _run_single_worker,
            task,
            **worker_kwargs,
            max_steps=worker_step_budgets.get(str(task.get("id") or "")),
          ): str(task["id"])
          for task in wave_tasks
        }
        wave_deadline = worker_timeout * max(1, len(wave_tasks))
        try:
          completed_iter = as_completed(futures, timeout=wave_deadline)
          for future in completed_iter:
            task_id = futures[future]
            try:
              wave_results.append(future.result())
            except Exception as exc:
              emit(
                "agent.worker.failed",
                f"File Worker {task_id} failed: {exc}",
                status="failed",
                detail={"task_id": task_id, "error": str(exc)},
              )
              wave_results.append({"task_id": task_id, "status": "failed", "error": str(exc)})
        except FuturesTimeoutError:
          emit(
            "agent.parallel.wave.timeout",
            f"Wave {wave_index} exceeded {wave_deadline}s — marking pending workers as failed",
            status="failed",
            detail={"wave": wave_index, "timeout_seconds": wave_deadline},
          )
        for future, task_id in futures.items():
          if future.done():
            continue
          future.cancel()
          shared_memory.publish_completion(
            task_id=task_id,
            agent_label=f"File Worker {task_id}",
            paths=[],
            summary=f"Worker timed out after {wave_deadline}s",
            status="failed",
          )
          emit(
            "agent.worker.failed",
            f"File Worker {task_id} timed out after {wave_deadline}s",
            status="failed",
            detail={"task_id": task_id, "timeout_seconds": wave_deadline},
          )
          wave_results.append(
            {
              "task_id": task_id,
              "status": "failed",
              "error": f"Worker timed out after {wave_deadline}s",
            }
          )
    worker_results.extend(wave_results)
    raise_if_project_cancelled(project_id)
    for item in wave_results:
      runtime = (item.get("result") or {}).get("runtime") or {}
      all_tool_calls.extend(runtime.get("tool_calls") or [])

    staged_snapshot = shared_memory.snapshot_files()
    wave_paths = _wave_changed_paths(wave_results, files_before=files_map, staged=staged_snapshot)
    syntax_issues = _run_wave_syntax_checkpoint(changed_paths=wave_paths, staged=staged_snapshot, emit=emit)
    _emit_wave_orchestration_checkpoint(
      wave_index=wave_index,
      wave_count=len(waves),
      wave_results=wave_results,
      shared_memory=shared_memory,
      work_plan=work_plan,
      syntax_issues=syntax_issues,
      emit=emit,
    )
    if work_plan.get("greenfield") and wave_index == 1 and wave_paths:
      emit(
        "files.staged.wave",
        f"Kept {len(wave_paths)} first-wave file(s) in shared staging until automated tests pass",
        status="completed",
        detail={"paths": wave_paths, "wave": wave_index, "files_committed": False},
      )

    emit(
      "agent.parallel.wave.completed",
      f"Wave {wave_index} finished",
      status="completed",
      detail={"wave": wave_index, "results": [{"task_id": r.get("task_id"), "status": r.get("status")} for r in wave_results]},
    )

  staged = shared_memory.snapshot_files()
  changed_paths = sorted(
    path for path, content in staged.items() if files_map.get(path, "") != content
  )
  write_payload = [{"path": path, "content": staged[path]} for path in changed_paths]
  last_local_sync: dict[str, Any] | None = None
  fallback_applied = False

  files_after_map = dict(files_map)
  files_after_map.update(staged)
  update_validation = None
  if intent == "website_update":
    from .update_validation import apply_brand_rename_fallback, extract_rename_target, validate_brand_rename

    update_validation = validate_brand_rename(
      prompt,
      files_before=files_map,
      files_after=files_after_map,
      changed_paths=changed_paths,
    )
    if update_validation and not update_validation.get("applied"):
      target = extract_rename_target(prompt)
      if target:
        fallback_payload, fallback_paths = apply_brand_rename_fallback(files_after_map, target_name=target)
        if fallback_payload:
          emit(
            "agent.fallback.brand_rename",
            f"Applying deterministic brand rename to {len(fallback_paths)} file(s)",
            status="completed",
            detail={"paths": fallback_paths, "target": target},
          )
          write_payload = fallback_payload
          changed_paths = fallback_paths
          for item in fallback_payload:
            staged[item["path"]] = item["content"]
            shared_memory.update_file(item["path"], item["content"])
          files_after_map = dict(files_map)
          files_after_map.update({item["path"]: item["content"] for item in fallback_payload})
          update_validation = validate_brand_rename(
            prompt,
            files_before=files_map,
            files_after=files_after_map,
            changed_paths=changed_paths,
          )
          update_validation["fallback_applied"] = True
          fallback_applied = True

  if intent in {"website_generation", "website_update"}:
    try:
      try:
        from ..agent_runtime.scaffolding import ensure_vite_scaffold_files
        from ..project_workspace import needs_vite_scaffold_repair
      except ImportError:
        from agents.agent_runtime.scaffolding import ensure_vite_scaffold_files
        from agents.project_workspace import needs_vite_scaffold_repair
      merged_for_scaffold = dict(files_map)
      merged_for_scaffold.update(staged)
      scaffold_input = [{"path": path, "content": content} for path, content in sorted(merged_for_scaffold.items())]
      if needs_vite_scaffold_repair(scaffold_input):
        scaffolded, scaffold_paths = ensure_vite_scaffold_files(
          scaffold_input,
          title=project_name or "Generated Website",
        )
        for item in scaffolded:
          staged[item["path"]] = item["content"]
          shared_memory.update_file(item["path"], item["content"])
        changed_paths = sorted(path for path, content in staged.items() if files_map.get(path, "") != content)
        write_payload = [{"path": path, "content": staged[path]} for path in changed_paths]
        if scaffold_paths:
          emit(
            "scaffold.repaired",
            f"Repaired {len(scaffold_paths)} required Vite scaffold file(s) before save",
            status="completed",
            detail={"paths": scaffold_paths},
          )
    except Exception:
      pass

  if write_payload and intent == "website_update":
    try:
      from .update_write_guard import filter_streaming_write_payload
    except ImportError:
      from agents.streaming.update_write_guard import filter_streaming_write_payload
    update_mode = str((update_analysis or {}).get("update_mode") or "")
    write_payload, rejected_writes = filter_streaming_write_payload(
      files_map,
      write_payload,
      update_mode=update_mode,
      prompt=prompt,
    )
    if rejected_writes:
      rejected_paths = {str(item.get("path") or "") for item in rejected_writes if item.get("path")}
      for path in rejected_paths:
        if path in staged:
          staged[path] = files_map.get(path, staged[path])
          shared_memory.update_file(path, files_map.get(path, ""))
      changed_paths = [path for path in changed_paths if path not in rejected_paths]
      emit(
        "update.rewrite.blocked",
        f"Blocked {len(rejected_writes)} destructive parallel worker rewrite(s)",
        status="completed",
        detail={"rejected": rejected_writes, "kept_paths": [item["path"] for item in write_payload]},
      )

  precommit_build_result: dict[str, Any] | None = None
  precommit_visual_result: dict[str, Any] | None = None
  precommit_attempted = False
  if write_payload:
    raise_if_project_cancelled(project_id)
    try:
      from .streaming_parity import streaming_patch_approval_gate

      approval_result = streaming_patch_approval_gate(
        tool_context=tool_context,
        user=user,
        project_id=project_id,
        prompt=prompt,
        write_payload=write_payload,
        files_before_map=files_map,
        emit_progress=emit,
        patch_action=patch_action,
        summary="Parallel file workers proposed changes.",
      )
      if approval_result is not None:
        runtime = dict(approval_result.get("runtime") or {})
        runtime.update(
          {
            "engine": "parallel_file_workers",
            "work_plan": work_plan,
            "worker_results": worker_results,
            "shared_memory": shared_memory.to_dict(),
            "tool_calls": all_tool_calls,
            "wave_count": len(waves),
            "worker_count": len(tasks),
          }
        )
        approval_result["runtime"] = runtime
        return approval_result
    except Exception:
      pass
    try:
      from .syntax_guard import find_syntax_issues_in_payload
    except ImportError:
      from agents.streaming.syntax_guard import find_syntax_issues_in_payload
    syntax_issues = find_syntax_issues_in_payload(write_payload)
    if syntax_issues:
      emit(
        "gate.syntax.commit_blocked",
        f"Blocked commit for {len(syntax_issues)} syntax issue(s)",
        status="failed",
        detail={
          "issues": syntax_issues[:8],
          "files_committed": False,
          "user_message": "File save blocked due to syntax errors. Fix the listed issues and retry.",
        },
      )
      write_payload = []
    # Website updates persist validated edits first, then use the post-update
    # build/QA stage below. This keeps a usable staged patch from being erased
    # by precommit automation before local/store persistence.
    if write_payload and intent == "website_generation" and hasattr(tool_context.store, "create_version"):
      raise_if_project_cancelled(project_id)
      try:
        try:
          from ..agent_runtime.scaffolding import (
            ensure_tailwind_runtime_files,
            ensure_vite_scaffold_files,
            normalize_frontend_runtime_imports,
          )
        except ImportError:
          from agents.agent_runtime.scaffolding import (
            ensure_tailwind_runtime_files,
            ensure_vite_scaffold_files,
            normalize_frontend_runtime_imports,
          )
        write_payload, _ = normalize_frontend_runtime_imports(write_payload)
        if intent != "website_update":
          write_payload, _ = ensure_tailwind_runtime_files(write_payload)
        write_payload = [
          item
          for item in write_payload
          if files_map.get(str(item.get("path") or "")) != str(item.get("content") or "")
        ]
        changed_paths = sorted(
          str(item.get("path") or "")
          for item in write_payload
          if str(item.get("path") or "").strip()
        )
      except Exception:
        pass
      try:
        from .streaming_visual_qa import run_precommit_automation_gate

        candidate_map = dict(files_map)
        candidate_map.update({str(item["path"]): str(item["content"]) for item in write_payload})
        precommit_attempted = True
        precommit_build_result, precommit_visual_result = run_precommit_automation_gate(
          project_id=project_id,
          user=user,
          tool_context=tool_context,
          candidate_files=[
            {"path": path, "content": content}
            for path, content in sorted(candidate_map.items())
          ],
          changed_paths=changed_paths,
          operation="update" if intent == "website_update" else "generation",
          prompt=prompt,
          chat_session_id=chat_session_id,
          agent_run_id=agent_run_id,
          emit_progress=emit_progress,
        )
        if (
          str(precommit_build_result.get("status") or "") != "ready"
          or str((precommit_visual_result or {}).get("status") or "") != "passed"
        ):
          write_payload = []
          changed_paths = []
        else:
          normalized_candidates = list(precommit_build_result.get("candidate_files") or [])
          normalized_map = {
            str(item.get("path") or ""): str(item.get("content") or "")
            for item in normalized_candidates
            if isinstance(item, dict) and item.get("path")
          }
          for path in precommit_build_result.get("normalization_paths") or []:
            if path in normalized_map:
              staged[path] = normalized_map[path]
              shared_memory.update_file(path, normalized_map[path])
              if path not in changed_paths:
                changed_paths.append(path)
          write_payload = [
            {"path": path, "content": content}
            for path, content in sorted(normalized_map.items())
            if files_map.get(path) != content
          ]
          changed_paths = [item["path"] for item in write_payload]
      except Exception as exc:
        precommit_attempted = True
        precommit_build_result = {"status": "failed", "error": str(exc), "precommit": True}
        emit(
          "automation.precommit.failed",
          f"Automated pre-commit testing failed: {exc}",
          status="failed",
          detail={"error": str(exc), "files_committed": False},
        )
        write_payload = []
        changed_paths = []
    if write_payload:
      raise_if_project_cancelled(project_id)
      emit("files.persisting", f"Saving {len(write_payload)} merged parallel worker files")
      write_result = upsert_project_files_tool(
        tool_context,
        user,
        {
          "project_id": project_id,
          "files": write_payload,
          "reason": "parallel_file_workers",
          "intent": intent,
        },
      )
      files_map.update({item["path"]: item["content"] for item in write_payload})
      if isinstance(write_result.get("local_sync"), dict):
        last_local_sync = write_result["local_sync"]
      emit(
        "files.persisted",
        f"Saved {len(write_payload)} files from parallel workers",
        status="completed",
        detail={
          "file_count": len(write_payload),
          "paths": [item["path"] for item in write_payload],
          "files": write_payload,
          "local_sync": last_local_sync,
          "fallback_applied": fallback_applied,
        },
      )
  elif fallback_applied:
    emit(
      "files.persist.skipped",
      "No files to persist after parallel workers and brand rename fallback",
      status="completed",
      detail={"changed_paths": changed_paths},
    )

  build_gate_result: dict[str, Any] | None = precommit_build_result
  visual_qa_result: dict[str, Any] | None = precommit_visual_result
  if (
    changed_paths
    and write_payload
    and not precommit_attempted
    and intent in {"website_update", "website_generation"}
  ):
    try:
      from .build_gate import post_update_build_gate_enabled, run_post_update_build_gate

      if post_update_build_gate_enabled():
        build_gate_result = run_post_update_build_gate(
          project_id=project_id,
          user=user,
          tool_context=tool_context,
          prompt=prompt,
          intent=intent,
          artifact_provider=artifact_provider,
          emit_progress=emit_progress,
          changed_paths=changed_paths,
          max_repair_attempts=1 if intent == "website_generation" else None,
          max_build_attempts=2 if intent == "website_generation" else None,
        )
        if build_gate_result.get("repair_attempts"):
          refreshed = {
            str(item.get("path") or ""): str(item.get("content") or "")
            for item in tool_context.store.list_files(project_id, user)
            if isinstance(item, dict) and item.get("path")
          }
          repair_paths = [path for path in refreshed if files_map.get(path, "") != refreshed.get(path, "")]
          if repair_paths:
            changed_paths = sorted(set(changed_paths) | set(repair_paths))
            write_payload = [{"path": path, "content": refreshed[path]} for path in changed_paths]
            staged.update({path: refreshed[path] for path in repair_paths})
        if build_gate_result.get("status") == "ready":
          try:
            from .streaming_visual_qa import run_post_update_visual_qa

            visual_qa_result = run_post_update_visual_qa(
              project_id=project_id,
              user=user,
              tool_context=tool_context,
              build_gate_result=build_gate_result,
              emit_progress=emit_progress,
              changed_paths=changed_paths,
              chat_session_id=chat_session_id,
              agent_run_id=agent_run_id,
              prompt=prompt,
              operation="update" if intent == "website_update" else "generation",
            )
          except Exception as exc:
            emit(
              "gate.visual_qa.failed",
              f"Post-update visual QA error: {exc}",
              status="failed",
              detail={
                "error": str(exc),
                "category": "visual_qa",
                "code": "visual_qa_failed",
                "user_message": "Files were saved locally. Visual QA did not pass — open Preview to review layout and styling.",
                "files_committed": True,
                "suggested_actions": [
                  "Open the preview and describe what looks wrong.",
                  "Ask the agent to fix layout, styling, or missing sections.",
                ],
              },
            )
        elif str(build_gate_result.get("status") or "").lower() not in {"ready", "skipped"}:
          try:
            from .commit_policy import should_rollback_after_build_gate
            from .streaming_parity import _rollback_changed_paths

            if should_rollback_after_build_gate(build_gate_result):
              _rollback_changed_paths(
                tool_context=tool_context,
                user=user,
                project_id=project_id,
                changed_paths=changed_paths,
                files_before_map=files_map,
                emit_progress=emit,
                build_gate_result=build_gate_result,
                persist_reason="parallel_file_workers",
              )
              write_payload = []
          except Exception:
            pass
    except Exception as exc:
      try:
        from .commit_policy import BUILD_FAILED_FILES_COMMITTED_MESSAGE
      except ImportError:
        from agents.streaming.commit_policy import BUILD_FAILED_FILES_COMMITTED_MESSAGE
      emit(
        "gate.build.failed",
        f"Post-update build gate error: {exc}",
        status="failed",
        detail={
          "error": str(exc),
          "category": "preview_build",
          "code": "build_gate_failed",
          "files_committed": True,
          "user_message": BUILD_FAILED_FILES_COMMITTED_MESSAGE,
          "suggested_actions": [
            "Your updated files are already saved — open them in the file tree.",
            "Retry Preview when your network or build environment is stable.",
          ],
        },
      )

  summaries = [
    str((item.get("result") or {}).get("runtime", {}).get("output_text") or "").strip()
    for item in worker_results
    if (item.get("result") or {}).get("runtime", {}).get("output_text")
  ]
  combined_summary = "\n".join(summary for summary in summaries if summary) or "Parallel file workers completed."
  if fallback_applied and update_validation and update_validation.get("applied"):
    combined_summary = (
      f"Applied brand rename fallback to {', '.join(changed_paths)}. "
      f"{combined_summary}".strip()
    )

  from .file_agent import _build_generated_website

  generated_website = _build_generated_website(
    write_payload or [{"path": p, "content": staged[p]} for p in changed_paths],
    summary=combined_summary,
  )

  runtime = {
    "engine": "parallel_file_workers",
    "work_plan": work_plan,
    "worker_results": worker_results,
    "shared_memory": shared_memory.to_dict(),
    "tool_calls": all_tool_calls,
    "changed_paths": changed_paths,
    "output_text": combined_summary,
    "wave_count": len(waves),
    "worker_count": len(tasks),
    "worker_step_budgets": worker_step_budgets,
    "model_call_budget": _request_model_call_budget(intent=intent),
    "local_sync": last_local_sync,
    "fallback_applied": fallback_applied,
  }
  if update_validation:
    runtime["update_validation"] = update_validation
  if build_gate_result:
    runtime["build_gate"] = build_gate_result
    final_output: dict[str, Any] = {
      "preview_status": build_gate_result.get("status"),
      "preview_url": build_gate_result.get("preview_url"),
      "preview": {
        "status": build_gate_result.get("status"),
        "preview_url": build_gate_result.get("preview_url"),
        "version_id": build_gate_result.get("version_id"),
        "build_log": build_gate_result.get("build_log"),
      },
    }
    if visual_qa_result:
      runtime["visual_qa"] = visual_qa_result
      final_output["visual_qa_status"] = visual_qa_result.get("status")
    runtime["final_output"] = final_output
    runtime["repair_iterations"] = int(
      build_gate_result.get("repair_iterations")
      if build_gate_result.get("repair_iterations") is not None
      else build_gate_result.get("repair_attempts") or 0
    )
    if str(build_gate_result.get("status") or "").lower() not in {"ready", "skipped"}:
      runtime["status"] = "failed"
      runtime["output_text"] = (
        f"{combined_summary}\n\nThe website files were generated, but preview verification failed after "
        f"{runtime['repair_iterations']} repair iteration(s)."
      ).strip()

  artifact_response = {
    "summary": combined_summary,
    "files": write_payload,
    "changed_paths": changed_paths,
    "changed_file_paths": changed_paths,
  }
  if update_validation:
    artifact_response["update_validation"] = update_validation

  return {
    "generated_website": generated_website,
    "artifact_response": artifact_response,
    "runtime": runtime,
  }
