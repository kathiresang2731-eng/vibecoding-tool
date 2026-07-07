from __future__ import annotations

import os
import re
from typing import Any, Callable

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

ProgressCallback = Callable[..., None]

BUILD_ERROR_PATH_RE = re.compile(
  r"(?P<path>(?:\.?/)?(?:src/|backend/|app/|index\.html)[A-Za-z0-9_./-]*\.(?:jsx|tsx|js|ts|html)):(?P<line>\d+)(?::(?P<col>\d+))?",
  re.IGNORECASE,
)

BUILD_ERROR_LINE_RE = re.compile(
  r"(?P<path>(?:\.?/)?(?:src/|backend/|app/|index\.html)[A-Za-z0-9_./-]*\.(?:jsx|tsx|js|ts|html)):(?P<line>\d+)(?::(?P<col>\d+))?\s*:?\s*(?P<message>ERROR[^\n]*)",
  re.IGNORECASE,
)


def post_update_build_gate_enabled() -> bool:
  try:
    from ..runtime_config import post_update_build_gate_enabled as _enabled
  except ImportError:
    from agents.runtime_config import post_update_build_gate_enabled as _enabled
  return _enabled()


def _max_repair_attempts() -> int:
  return max(0, int(os.getenv("POST_UPDATE_BUILD_GATE_MAX_REPAIRS", "2")))


def _max_build_attempts() -> int:
  return max(1, int(os.getenv("POST_UPDATE_BUILD_GATE_MAX_BUILDS", "4")))


def _list_tool_files(tool_context: Any, user: UserContext, project_id: str) -> list[dict[str, str]]:
  return [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in tool_context.store.list_files(project_id, user)
    if isinstance(item, dict) and item.get("path")
  ]


def _project_title(tool_context: Any, user: UserContext, project_id: str) -> str:
  project = tool_context.store.get_project(project_id, user) if tool_context.store else None
  if isinstance(project, dict):
    name = str(project.get("name") or "").strip()
    if name:
      return name
  return "Generated Website"


def parse_build_error_paths(build_log: str, *, max_paths: int = 4) -> list[str]:
  paths: list[str] = []
  for match in BUILD_ERROR_PATH_RE.finditer(str(build_log or "")):
    path = match.group("path").replace("\\", "/")
    if path.startswith("./"):
      path = path[2:]
    if path.startswith("/"):
      path = path[1:]
    if path not in paths:
      paths.append(path)
    if len(paths) >= max_paths:
      break
  if len(paths) < max_paths:
    quoted_module_paths = re.findall(
      r"[\"'](?P<path>/?(?:src/|backend/|app/)[A-Za-z0-9_./-]*\.(?:jsx|tsx|js|ts|html))[\"']",
      str(build_log or ""),
      re.IGNORECASE,
    )
    for path in quoted_module_paths:
      normalized = path.replace("\\", "/")
      if normalized.startswith("/"):
        normalized = normalized[1:]
      if normalized not in paths:
        paths.append(normalized)
      if len(paths) >= max_paths:
        break
  return paths


def parse_build_error_locations(build_log: str, *, max_results: int = 3) -> list[dict[str, Any]]:
  locations: list[dict[str, Any]] = []
  seen: set[str] = set()
  for match in BUILD_ERROR_LINE_RE.finditer(str(build_log or "")):
    path = match.group("path").replace("\\", "/")
    if path.startswith("./"):
      path = path[2:]
    if path.startswith("/"):
      path = path[1:]
    line = int(match.group("line") or 0)
    key = f"{path}:{line}"
    if key in seen:
      continue
    seen.add(key)
    locations.append(
      {
        "path": path,
        "line": line,
        "col": int(match.group("col") or 0) if match.group("col") else None,
        "message": str(match.group("message") or "").strip(),
      }
    )
    if len(locations) >= max_results:
      break
  return locations


def _snippet_around_line(content: str, line: int, *, radius: int = 18) -> str:
  lines = content.splitlines()
  if not lines:
    return content[:8_000]
  index = max(0, min(len(lines) - 1, line - 1))
  start = max(0, index - radius)
  end = min(len(lines), index + radius + 1)
  numbered = [f"{offset + 1:4d}| {lines[offset]}" for offset in range(start, end)]
  return "\n".join(numbered)


def build_targeted_repair_prompt(
  *,
  original_prompt: str,
  build_log: str,
  repair_reason: str,
  files_map: dict[str, str],
) -> tuple[str, list[str]]:
  locations = parse_build_error_locations(build_log)
  error_paths = [loc["path"] for loc in locations] or parse_build_error_paths(build_log)
  if not error_paths:
    return build_repair_prompt(original_prompt=original_prompt, build_log=build_log, repair_reason=repair_reason), []

  blocks: list[str] = [
    "Build error after website update. Fix ONLY the listed error file(s) so Vite build passes.",
    "Use str_replace or write_file on the assigned path(s) only. Do not read unrelated files.",
    f"\nOriginal request:\n{original_prompt[:1_500]}",
    f"\nBuild failure:\n{repair_reason}",
  ]
  for loc in locations[:4]:
    path = loc["path"]
    content = files_map.get(path, "")
    if not content:
      continue
    blocks.append(
      f"\n### `{path}` — error at line {loc['line']}: {loc.get('message') or 'syntax error'}\n"
      f"```\n{_snippet_around_line(content, loc['line'])}\n```"
    )
  for path in error_paths[:4]:
    if any(loc["path"] == path for loc in locations):
      continue
    content = files_map.get(path, "")
    if content:
      blocks.append(f"\n### `{path}`\n```\n{content[:12_000]}\n```")
  blocks.append(f"\nBuild log excerpt:\n{str(build_log or '')[-6_000:]}")
  return "\n".join(blocks), error_paths[:4]


def normalize_files_before_build(
  files: list[dict[str, Any]],
  *,
  title: str = "Generated Website",
) -> tuple[list[dict[str, str]], list[str]]:
  try:
    from ..agent_runtime.progress import normalize_candidate_react_imports
    from ..agent_runtime.scaffolding import (
      ensure_tailwind_runtime_files,
      ensure_vite_scaffold_files,
      normalize_frontend_runtime_imports,
    )
    from ..project_workspace import needs_vite_scaffold_repair
  except ImportError:
    from agents.agent_runtime.progress import normalize_candidate_react_imports
    from agents.agent_runtime.scaffolding import (
      ensure_tailwind_runtime_files,
      ensure_vite_scaffold_files,
      normalize_frontend_runtime_imports,
    )
    from agents.project_workspace import needs_vite_scaffold_repair

  touched: list[str] = []
  current = [dict(item) for item in files if isinstance(item, dict) and item.get("path")]
  scaffolded, scaffold_paths = (current, [])
  if needs_vite_scaffold_repair(current):
    scaffolded, scaffold_paths = ensure_vite_scaffold_files(current, title=title)
  current = scaffolded
  touched.extend(scaffold_paths)
  tailwind_files, tailwind_paths = ensure_tailwind_runtime_files(current)
  current = tailwind_files
  touched.extend(tailwind_paths)
  normalized, react_paths = normalize_candidate_react_imports(current)
  current = normalized
  touched.extend(react_paths)
  runtime_files, runtime_paths = normalize_frontend_runtime_imports(current)
  current = runtime_files
  touched.extend(runtime_paths)
  try:
    from .module_contracts import normalize_relative_import_export_contracts

    contract_files, contract_paths, _ = normalize_relative_import_export_contracts(current)
    current = contract_files
    touched.extend(contract_paths)
  except Exception:
    pass
  return current, list(dict.fromkeys(touched))


def apply_deterministic_build_repair(
  files: list[dict[str, Any]],
  repair_reason: str,
  *,
  title: str = "Generated Website",
) -> tuple[list[dict[str, str]], list[str], str | None]:
  try:
    from ..agent_runtime.actions.project_io import is_unresolved_preview_runtime_import_reason
    from ..agent_runtime.progress import (
      is_missing_vite_entry_reason,
      is_unsafe_bare_react_reason,
      normalize_candidate_react_imports,
      preview_build_failure_reason,
    )
    from ..agent_runtime.scaffolding import (
      ensure_vite_scaffold_files,
      normalize_frontend_runtime_imports,
    )
    from ..project_workspace import needs_vite_scaffold_repair
  except ImportError:
    from agents.agent_runtime.actions.project_io import is_unresolved_preview_runtime_import_reason
    from agents.agent_runtime.progress import (
      is_missing_vite_entry_reason,
      is_unsafe_bare_react_reason,
      normalize_candidate_react_imports,
      preview_build_failure_reason,
    )
    from agents.agent_runtime.scaffolding import (
      ensure_vite_scaffold_files,
      normalize_frontend_runtime_imports,
    )
    from agents.project_workspace import needs_vite_scaffold_repair

  reason = preview_build_failure_reason(repair_reason)
  current = [dict(item) for item in files if isinstance(item, dict) and item.get("path")]

  if is_missing_vite_entry_reason(reason) and needs_vite_scaffold_repair(current):
    scaffolded, paths = ensure_vite_scaffold_files(current, title=title)
    if paths:
      return scaffolded, paths, "vite_scaffold"

  if is_unsafe_bare_react_reason(reason):
    normalized, paths = normalize_candidate_react_imports(current)
    if paths:
      return normalized, paths, "react_imports"

  runtime_files, paths = normalize_frontend_runtime_imports(current)
  if is_unresolved_preview_runtime_import_reason(reason) and paths:
    return runtime_files, paths, "runtime_imports"

  try:
    from .module_contracts import normalize_relative_import_export_contracts

    contract_files, contract_paths, _ = normalize_relative_import_export_contracts(current)
    if contract_paths:
      return contract_files, contract_paths, "module_contracts"
  except Exception:
    pass

  return current, [], None


def build_repair_prompt(*, original_prompt: str, build_log: str, repair_reason: str) -> str:
  excerpt = str(build_log or "")[-4000:]
  error_paths = parse_build_error_paths(build_log)
  path_hint = f"\nLikely files: {', '.join(error_paths)}" if error_paths else ""
  return (
    "Build error after website update. Fix the smallest root cause so the Vite production build passes.\n\n"
    f"Original request:\n{original_prompt[:900]}\n\n"
    f"Build failure summary:\n{repair_reason}\n"
    f"{path_hint}\n\n"
    f"Build log excerpt:\n{excerpt}"
  )


def _run_staged_build(
  tool_context: Any,
  user: UserContext,
  project_id: str,
  files: list[dict[str, str]],
) -> dict[str, Any]:
  try:
    from ...agentic.tools.handlers import build_staged_project_preview_tool
  except ImportError:
    from agentic.tools.handlers import build_staged_project_preview_tool
  return build_staged_project_preview_tool(
    tool_context,
    user,
    {"project_id": project_id, "files": files},
  )


def _persist_files(
  tool_context: Any,
  user: UserContext,
  project_id: str,
  files: list[dict[str, str]],
  *,
  reason: str,
) -> dict[str, Any] | None:
  if not files:
    return None
  try:
    from ...agentic.tools.handlers import upsert_project_files_tool
  except ImportError:
    from agentic.tools.handlers import upsert_project_files_tool
  return upsert_project_files_tool(
    tool_context,
    user,
    {"project_id": project_id, "files": files, "reason": reason},
  )


def run_post_update_build_gate(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  changed_paths: list[str] | None = None,
  max_repair_attempts: int | None = None,
  max_build_attempts: int | None = None,
) -> dict[str, Any]:
  if not post_update_build_gate_enabled():
    return {"status": "skipped", "reason": "disabled"}
  if intent not in {"website_update", "website_generation"}:
    return {"status": "skipped", "reason": f"intent={intent}"}
  if changed_paths is not None and not changed_paths:
    return {"status": "skipped", "reason": "no_changed_paths"}

  try:
    from ..agent_runtime.progress import preview_build_failure_reason
  except ImportError:
    from agents.agent_runtime.progress import preview_build_failure_reason

  emit_progress(
    "gate.build.started",
    "Running staged Vite build to verify generated files",
    status="running",
    detail={"project_id": project_id, "intent": intent},
  )

  title = _project_title(tool_context, user, project_id)
  files = _list_tool_files(tool_context, user, project_id)
  if not files:
    emit_progress("gate.build.skipped", "No project files available for build gate", status="completed")
    return {"status": "skipped", "reason": "no_files"}

  normalized_files, pre_touch = normalize_files_before_build(files, title=title)
  deterministic_repairs: list[str] = []
  repair_attempts = 0
  repair_limit = _max_repair_attempts() if max_repair_attempts is None else max(0, int(max_repair_attempts))
  build_limit = _max_build_attempts() if max_build_attempts is None else max(1, int(max_build_attempts))

  def run_hidden_build(attempt: int) -> dict[str, Any]:
    emit_progress(
      "terminal.command.started",
      f"Hidden terminal: npm run build (attempt {attempt}/{build_limit})",
      status="running",
      detail={
        "command": "npm run build",
        "hidden_terminal": True,
        "attempt": attempt,
        "max_attempts": build_limit,
      },
    )
    result = _run_staged_build(tool_context, user, project_id, files)
    result_version = result.get("version") if isinstance(result.get("version"), dict) else {}
    result_status = str(result_version.get("status") or "failed")
    emit_progress(
      "terminal.command.completed",
      f"Hidden terminal build {'passed' if result_status == 'ready' else 'failed'}",
      status="completed" if result_status == "ready" else "failed",
      detail={
        "command": "npm run build",
        "hidden_terminal": True,
        "attempt": attempt,
        "exit_status": result_status,
        "preview_url": result_version.get("preview_url"),
        "output": str(result_version.get("build_log") or "")[-4_000:],
      },
    )
    return result

  if pre_touch:
    _persist_files(tool_context, user, project_id, normalized_files, reason="build_gate_normalize")
    files = normalized_files
    deterministic_repairs.append("pre_build_normalization")
    emit_progress(
      "gate.deterministic.normalized",
      f"Applied pre-build normalization to {len(pre_touch)} file(s)",
      status="completed",
      detail={"paths": pre_touch},
    )

  preview_result = run_hidden_build(1)
  version = preview_result.get("version") if isinstance(preview_result.get("version"), dict) else {}
  build_log = str(version.get("build_log") or "")
  build_status = str(version.get("status") or "failed")
  applied_deterministic: set[str] = set()
  build_attempts = 1

  while build_status != "ready" and build_attempts < build_limit:
    repair_reason = preview_build_failure_reason(build_log)
    repaired_files, repair_paths, strategy = apply_deterministic_build_repair(files, repair_reason, title=title)
    if strategy and repair_paths and strategy not in applied_deterministic:
      applied_deterministic.add(strategy)
      deterministic_repairs.append(strategy)
      _persist_files(tool_context, user, project_id, repaired_files, reason=f"build_gate_{strategy}")
      files = _list_tool_files(tool_context, user, project_id)
      emit_progress(
        "gate.deterministic.repair",
        f"Applied deterministic {strategy} repair",
        status="completed",
        detail={"paths": repair_paths, "strategy": strategy, "repair_reason": repair_reason[:800]},
      )
      if build_attempts >= build_limit:
        break
      build_attempts += 1
      preview_result = run_hidden_build(build_attempts)
      version = preview_result.get("version") if isinstance(preview_result.get("version"), dict) else {}
      build_log = str(version.get("build_log") or "")
      build_status = str(version.get("status") or "failed")
      if build_status == "ready":
        break
      continue

    if repair_attempts >= repair_limit:
      break

    repair_attempts += 1
    files_map = {item["path"]: item["content"] for item in files}
    repair_prompt, error_paths = build_targeted_repair_prompt(
      original_prompt=prompt,
      build_log=build_log,
      repair_reason=repair_reason,
      files_map=files_map,
    )
    if not error_paths:
      emit_progress(
        "gate.repair.skipped",
        "Could not locate a failing file in the build log — skipping LLM repair",
        status="completed",
        detail={"repair_reason": repair_reason[:800]},
      )
      break

    emit_progress(
      "gate.repair.started",
      f"Repair agent fixing {', '.join(error_paths)} (attempt {repair_attempts}/{repair_limit})",
      status="running",
      detail={"repair_reason": repair_reason[:1200], "attempt": repair_attempts, "paths": error_paths},
    )

    from .file_agent import run_streaming_file_agent

    repair_result = run_streaming_file_agent(
      project_id=project_id,
      user=user,
      tool_context=tool_context,
      prompt=repair_prompt,
      intent="website_update",
      artifact_provider=artifact_provider,
      emit_progress=emit_progress,
      max_steps=int(os.getenv("BUILD_GATE_REPAIR_MAX_STEPS", "4")),
      skip_workspace_pull=True,
      skip_build_gate=True,
      allowed_write_paths=frozenset(error_paths),
      worker_id="build-gate-repair",
    )
    repair_runtime = repair_result.get("runtime") if isinstance(repair_result.get("runtime"), dict) else {}
    repair_changed = list(repair_runtime.get("changed_paths") or [])
    emit_progress(
      "gate.repair.completed",
      "Repair agent finished build-error pass",
      status="completed",
      detail={
        "attempt": repair_attempts,
        "changed_paths": repair_changed,
        "target_paths": error_paths,
        "output_text": str(repair_runtime.get("output_text") or "")[:600],
      },
    )
    if not repair_changed:
      emit_progress(
        "gate.repair.no_changes",
        "Repair agent made no file changes — stopping further build retries",
        status="completed",
        detail={"target_paths": error_paths},
      )
      break

    files = _list_tool_files(tool_context, user, project_id)
    if build_attempts >= build_limit:
      break
    build_attempts += 1
    preview_result = run_hidden_build(build_attempts)
    version = preview_result.get("version") if isinstance(preview_result.get("version"), dict) else {}
    build_log = str(version.get("build_log") or "")
    build_status = str(version.get("status") or "failed")

  repair_iterations = repair_attempts + len(
    [strategy for strategy in deterministic_repairs if strategy != "pre_build_normalization"]
  )
  result = {
    "status": build_status,
    "build_log": build_log,
    "preview_url": version.get("preview_url"),
    "version_id": version.get("id"),
    "repair_attempts": repair_attempts,
    "repair_iterations": repair_iterations,
    "build_attempts": build_attempts,
    "deterministic_repairs": deterministic_repairs,
    "error_paths": parse_build_error_paths(build_log),
  }

  if build_status == "ready":
    emit_progress(
      "gate.build.passed",
      "Staged Vite build passed — preview is ready",
      status="completed",
      detail={
        "preview_url": version.get("preview_url"),
        "version_id": version.get("id"),
        "repair_attempts": repair_attempts,
        "repair_iterations": repair_iterations,
        "deterministic_repairs": deterministic_repairs,
      },
    )
    emit_progress(
      "preview.built",
      "Preview build completed successfully",
      status="completed",
      detail={"preview_url": version.get("preview_url"), "source": "post_update_build_gate"},
    )
  else:
    final_reason = preview_build_failure_reason(build_log)
    try:
      from .commit_policy import build_gate_failure_detail
    except ImportError:
      from agents.streaming.commit_policy import build_gate_failure_detail
    failure_detail = build_gate_failure_detail(
      build_gate_result=result,
      rolled_back=False,
      repair_reason=final_reason[:1200],
      repair_attempts=repair_attempts,
      deterministic_repairs=deterministic_repairs,
      error_paths=result["error_paths"],
      build_log_excerpt=build_log[-2000:],
    )
    emit_progress(
      "gate.build.failed",
      f"Preview build failed after {repair_iterations} repair iteration(s): {final_reason[:240]}",
      status="failed",
      detail=failure_detail,
    )
    emit_progress(
      "error.diagnosed",
      "Build failed — repair budget exhausted",
      status="completed",
      detail={"issues": [final_reason], "error_paths": result["error_paths"]},
    )

  return result
