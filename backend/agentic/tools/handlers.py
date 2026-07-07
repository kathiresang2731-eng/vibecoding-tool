from __future__ import annotations

from typing import Any

try:
  from ...agents.artifacts import validate_project_artifact
  from ...local_workspace import LocalWorkspaceError, read_local_project_files, resolve_local_project_path, write_local_project_files
  from ...runtime import build_project_preview, build_staged_project_preview
  from ...storage import UserContext
  from ...visual_qa import prompt_requires_interaction_qa, run_browser_preview_qa
except ImportError:
  from agents.artifacts import validate_project_artifact
  from local_workspace import LocalWorkspaceError, read_local_project_files, resolve_local_project_path, write_local_project_files
  from runtime import build_project_preview, build_staged_project_preview
  from storage import UserContext
  from visual_qa import prompt_requires_interaction_qa, run_browser_preview_qa

from .definitions import ToolExecutionError, ToolRuntimeContext
from .project_files import invalidate_project_files_snapshot, snapshot_project_files
from .validators import optional_int, optional_string, required_files, required_string


def add_store_event_if_supported(
  context: ToolRuntimeContext,
  project_id: str,
  user: UserContext,
  event_type: str,
  payload: dict[str, Any],
) -> None:
  if hasattr(context.store, "add_event"):
    context.store.add_event(project_id, user.id, event_type, payload)


def _compatibility_export(name: str, fallback: Any) -> Any:
  try:
    from ... import agent_tools as agent_tools_facade

    return getattr(agent_tools_facade, name, fallback)
  except Exception:
    return fallback


def preview_url_for_test_route(preview_url: str, route: str, *, router_mode: str) -> str:
  normalized_route = str(route or "/").strip() or "/"
  if normalized_route == "/":
    return preview_url
  route_path = normalized_route if normalized_route.startswith("/") else f"/{normalized_route}"
  base = preview_url.split("#", 1)[0]
  if router_mode == "browser":
    return f"{base.rstrip('/')}{route_path}"
  return f"{base}#{route_path}"


def merge_route_visual_qa_results(results: list[dict[str, Any]]) -> dict[str, Any]:
  if not results:
    return {"status": "failed", "warnings": ["No route visual QA results were produced."]}
  merged = dict(results[0])
  merged["status"] = (
    "failed"
    if any(item.get("status") == "failed" for item in results)
    else "passed"
    if any(item.get("status") == "passed" for item in results)
    else "skipped"
  )
  merged["layout_checked"] = any(bool(item.get("layout_checked")) for item in results)
  merged["screenshots"] = [
    screenshot
    for item in results
    for screenshot in item.get("screenshots", [])
    if isinstance(screenshot, dict)
  ]
  merged["checks"] = [
    check
    for item in results
    for check in item.get("checks", [])
    if isinstance(check, dict)
  ]
  merged["warnings"] = [
    warning
    for item in results
    for warning in item.get("warnings", [])
    if isinstance(warning, str)
  ]
  merged["viewport_results"] = [
    {**viewport, "route": item.get("route") or "/"}
    for item in results
    for viewport in item.get("viewport_results", [])
    if isinstance(viewport, dict)
  ]
  merged["layout_issues"] = [
    {**issue, "route": item.get("route") or "/"}
    for item in results
    for issue in item.get("layout_issues", [])
    if isinstance(issue, dict)
  ]
  merged["severity"] = (
    "high"
    if any(item.get("severity") == "high" for item in results)
    else "medium"
    if any(item.get("severity") == "medium" for item in results)
    else "none"
  )
  merged["routes_checked"] = [str(item.get("route") or "/") for item in results]
  return merged


def pull_linked_workspace_to_store(
  context: ToolRuntimeContext,
  user: UserContext,
  *,
  project_id: str,
  source: str = "workspace_sync",
) -> dict[str, Any]:
  project = context.store.get_project(project_id, user) if hasattr(context.store, "get_project") else None
  local_path = project.get("local_path") if isinstance(project, dict) else None
  if isinstance(local_path, str) and local_path.strip() and context.settings is not None:
    local_root = resolve_local_project_path(context.settings, local_path)
    files = read_local_project_files(local_root)
    if files:
      context.store.replace_project_files(
        project_id,
        user,
        files,
        event_type="local.pulled",
        event_payload={"path": str(local_root), "source": source},
        allow_prune_missing=True,
      )
      invalidate_project_files_snapshot(context, user, project_id)
    else:
      files = snapshot_project_files(context, user, project_id, refresh=True)
    return {
      "project_id": project_id,
      "files": files,
      "file_count": len(files),
      "local_sync": {"direction": "pull", "path": str(local_root), "file_count": len(files), "source": source},
      "source": "local_pull",
    }

  files = snapshot_project_files(context, user, project_id)
  return {
    "project_id": project_id,
    "files": files,
    "file_count": len(files),
    "local_sync": None,
    "source": "store",
  }


def read_project_files_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  result = pull_linked_workspace_to_store(context, user, project_id=project_id, source="read_project_files")
  return {
    "project_id": project_id,
    "files": result["files"],
    "file_count": result["file_count"],
    "local_sync": result.get("local_sync"),
  }


def load_project_memory_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  namespace = optional_string(arguments, "namespace")
  limit = optional_int(arguments, "limit", fallback=12, minimum=1, maximum=50)
  if not hasattr(context.store, "list_memory_items"):
    return {"project_id": project_id, "memories": [], "memory_count": 0}
  memories = context.store.list_memory_items(user, project_id=project_id, namespace=namespace, limit=limit)
  compact = [
    {
      "namespace": item.get("namespace"),
      "key": item.get("key"),
      "kind": item.get("kind"),
      "content": item.get("content"),
      "updated_at": item.get("updated_at"),
    }
    for item in memories
    if isinstance(item, dict)
  ]
  return {"project_id": project_id, "memories": compact, "memory_count": len(compact)}


def persist_project_memory_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  namespace = optional_string(arguments, "namespace") or "agent"
  key = required_string(arguments, "key")
  kind = optional_string(arguments, "kind") or "summary"
  content = required_string(arguments, "content")
  metadata = arguments.get("metadata")
  if metadata is not None and not isinstance(metadata, dict):
    raise ToolExecutionError("metadata must be an object when provided.")
  if context.store is None or not hasattr(context.store, "upsert_memory_item"):
    return {
      "project_id": project_id,
      "status": "skipped",
      "reason": "Memory store is unavailable.",
      "namespace": namespace,
      "key": key,
      "kind": kind,
    }
  memory = context.store.upsert_memory_item(
    user,
    project_id=project_id,
    namespace=namespace,
    key=key,
    kind=kind,
    content=content,
    metadata=metadata or {"source": "tool_registry"},
  )
  return {
    "project_id": project_id,
    "status": "persisted",
    "memory_id": memory.get("id") if isinstance(memory, dict) else None,
    "namespace": namespace,
    "key": key,
    "kind": kind,
  }


def write_project_files_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  files = required_files(arguments.get("files"))
  if not files and not bool(arguments.get("allow_empty")):
    raise ToolExecutionError("Empty project file writes require allow_empty=true.")
  mode = str(arguments.get("mode") or "upsert").strip().lower()
  if mode not in {"upsert", "replace_all"}:
    raise ToolExecutionError("WRITE_PROJECT_FILES mode must be upsert or replace_all.")
  allow_prune_missing = bool(arguments.get("allow_prune_missing"))
  if mode == "replace_all" and not allow_prune_missing:
    raise ToolExecutionError("replace_all writes require allow_prune_missing=true so destructive replacement is explicit.")
  project = context.store.get_project(project_id, user)
  local_sync = None
  local_sync_error = None
  if mode == "replace_all":
    context.store.replace_project_files(
      project_id,
      user,
      files,
      event_type="agent.files.written",
      event_payload={"source": "tool_registry", "local_sync": local_sync, "mode": mode, "allow_prune_missing": allow_prune_missing},
      allow_prune_missing=allow_prune_missing,
    )
    invalidate_project_files_snapshot(context, user, project_id)
    file_count = len(files)
  elif not files:
    file_count = 0
    add_store_event_if_supported(
      context,
      project_id,
      user,
      "agent.files.upserted",
      {"count": 0, "source": "tool_registry", "local_sync": local_sync, "mode": mode},
    )
  elif hasattr(context.store, "upsert_project_files"):
    file_count = context.store.upsert_project_files(
      project_id,
      user,
      files,
      event_type="agent.files.upserted",
      event_payload={"source": "tool_registry", "local_sync": local_sync, "mode": mode},
    )
    invalidate_project_files_snapshot(context, user, project_id)
  else:
    for file_item in files:
      context.store.upsert_file(project_id, user, path=file_item["path"], content=file_item["content"], emit_event=False)
    file_count = len(files)
    invalidate_project_files_snapshot(context, user, project_id)
    add_store_event_if_supported(
      context,
      project_id,
      user,
      "agent.files.upserted",
      {"count": file_count, "source": "tool_registry", "local_sync": local_sync, "mode": mode},
    )
  if project and project.get("local_path"):
    try:
      if context.settings is None:
        raise ToolExecutionError("Cannot sync linked local project because backend settings are unavailable.")
      local_root = resolve_local_project_path(context.settings, str(project["local_path"]))
      count = write_local_project_files(
        local_root,
        files,
        prune_missing=mode == "replace_all",
        allow_prune_missing=allow_prune_missing,
      )
      local_sync = {"direction": "push", "path": str(local_root), "count": count, "mode": mode}
      add_store_event_if_supported(context, project_id, user, "local.files.written", {"path": local_sync["path"], "count": local_sync["count"], "mode": mode})
    except (LocalWorkspaceError, ToolExecutionError) as exc:
      local_sync_error = str(exc)
      add_store_event_if_supported(
        context,
        project_id,
        user,
        "local.files.write_failed",
        {"path": str(project.get("local_path") or ""), "error": local_sync_error, "mode": mode},
      )
  return {
    "project_id": project_id,
    "file_count": file_count,
    "requested_file_count": len(files),
    "persisted_file_count": file_count,
    "paths": [file_item["path"] for file_item in files if file_item.get("path")],
    "local_sync": local_sync,
    "local_sync_error": local_sync_error,
    "mode": mode,
  }


def upsert_project_files_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  files = required_files(arguments.get("files"))
  if not files:
    raise ToolExecutionError("upsert_project_files requires at least one file.")
  reason = str(arguments.get("reason") or "")
  intent = str(arguments.get("intent") or "")
  request_kind = str(arguments.get("request_kind") or "")
  if intent == "website_update":
    try:
      from ...agents.platform_file_locks import filter_locked_platform_writes
    except ImportError:
      from agents.platform_file_locks import filter_locked_platform_writes
    existing_map: dict[str, str] = {}
    if hasattr(context.store, "list_files"):
      for file_item in snapshot_project_files(context, user, project_id):
        path = str(file_item.get("path") or "").strip()
        if path:
          existing_map[path] = str(file_item.get("content") or "")
    files, _rejected = filter_locked_platform_writes(
      files,
      files_before_map=existing_map,
      intent=intent,
      persist_reason=reason,
      request_kind=request_kind,
    )
    if not files:
      raise ToolExecutionError("All requested file writes were blocked by platform file locks.")
  project = context.store.get_project(project_id, user)
  local_sync = None
  local_sync_error = None
  if not hasattr(context.store, "upsert_project_files"):
    for file_item in files:
      context.store.upsert_file(project_id, user, path=file_item["path"], content=file_item["content"], emit_event=False)
    file_count = len(files)
    context.store.add_event(
      project_id,
      user.id,
      "agent.files.upserted",
      {"count": file_count, "source": "tool_registry", "local_sync": local_sync},
    )
  else:
    file_count = context.store.upsert_project_files(
      project_id,
      user,
      files,
      event_type="agent.files.upserted",
      event_payload={"source": "tool_registry", "local_sync": local_sync},
    )
  invalidate_project_files_snapshot(context, user, project_id)
  if project and project.get("local_path"):
    try:
      if context.settings is None:
        raise ToolExecutionError("Cannot sync linked local project because backend settings are unavailable.")
      local_root = resolve_local_project_path(context.settings, str(project["local_path"]))
      count = write_local_project_files(local_root, files, prune_missing=False)
      local_sync = {"direction": "push", "path": str(local_root), "count": count}
      context.store.add_event(project_id, user.id, "local.files.written", {"path": local_sync["path"], "count": local_sync["count"]})
    except (LocalWorkspaceError, ToolExecutionError) as exc:
      local_sync_error = str(exc)
      context.store.add_event(
        project_id,
        user.id,
        "local.files.write_failed",
        {"path": str(project.get("local_path") or ""), "error": local_sync_error, "mode": "upsert"},
      )
  try:
    from ...agents.code_index.incremental import maybe_reindex_after_persist
  except ImportError:
    from agents.code_index.incremental import maybe_reindex_after_persist
  maybe_reindex_after_persist(
    project_id,
    files,
    changed_paths=[str(item.get("path") or "") for item in files if item.get("path")],
  )
  return {
    "project_id": project_id,
    "file_count": file_count,
    "requested_file_count": len(files),
    "persisted_file_count": file_count,
    "paths": [file_item["path"] for file_item in files if file_item.get("path")],
    "local_sync": local_sync,
    "local_sync_error": local_sync_error,
    "mode": "upsert",
  }


def validate_project_artifact_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  generated_website = arguments.get("generated_website")
  if not isinstance(generated_website, dict):
    raise ToolExecutionError("generated_website must be an object.")
  artifact = validate_project_artifact(generated_website)
  return {
    "status": "valid",
    "title": artifact["title"],
    "section_count": len(artifact["sections"]),
    "file_count": len(artifact["files"]),
    "paths": [file_item["path"] for file_item in artifact["files"]],
  }


def build_project_preview_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  version = build_project_preview(context.store, project_id, user, context.settings)
  return {"project_id": project_id, "version": version}


def build_staged_project_preview_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  files = required_files(arguments.get("files"))
  if not files:
    raise ToolExecutionError("staged preview files must be a non-empty list.")
  version = build_staged_project_preview(context.store, project_id, user, context.settings, files)
  return {"project_id": project_id, "version": version, "staged": True}


def run_preview_visual_qa_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  status = required_string(arguments, "status").lower()
  preview_url = optional_string(arguments, "preview_url")
  build_log = optional_string(arguments, "build_log") or ""
  operation = (optional_string(arguments, "operation") or "generation").lower()
  scope = (optional_string(arguments, "scope") or ("targeted" if operation == "update" else "full")).lower()
  chat_session_id = optional_string(arguments, "chat_session_id")
  generation_run_id = optional_string(arguments, "generation_run_id")
  agent_run_id = optional_string(arguments, "agent_run_id")
  project_version_id = optional_string(arguments, "project_version_id")
  route = optional_string(arguments, "route") or "/"
  router_mode = (optional_string(arguments, "router_mode") or "hash").lower()
  phase = (optional_string(arguments, "phase") or "after").lower()
  interaction_prompt = optional_string(arguments, "interaction_prompt") or ""
  changed_paths = [str(path) for path in arguments.get("changed_paths", []) if str(path).strip()]
  affected_routes = [str(path) for path in arguments.get("affected_routes", []) if str(path).strip()] or [route]
  if status != "ready":
    raise ToolExecutionError("Preview visual QA requires a ready staged preview.")

  warnings: list[str] = []
  checks = [
    {"name": "staged_preview_status", "status": "passed", "detail": "Preview build status is ready."},
  ]
  if preview_url:
    checks.append({"name": "preview_url_available", "status": "passed", "detail": preview_url})
  else:
    warnings.append("Preview URL is missing from the staged build output.")
    checks.append({"name": "preview_url_available", "status": "warning", "detail": "No preview URL was returned."})

  lower_log = build_log.lower()
  failure_markers = ["error:", "failed", "traceback", "syntaxerror", "referenceerror", "module not found"]
  matched_markers = [marker for marker in failure_markers if marker in lower_log]
  if matched_markers:
    raise ToolExecutionError(f"Preview QA found failure markers in build log: {', '.join(matched_markers)}")
  checks.append({"name": "build_log_failure_scan", "status": "passed", "detail": "No obvious failure markers found."})

  test_run = None
  screenshot_output_dir = None
  supports_persistence = all(
    hasattr(context.store, name)
    for name in (
      "create_automation_test_run",
      "create_screenshot_artifact",
      "create_visual_comparison",
      "complete_automation_test_run",
      "latest_baseline_screenshot",
    )
  )
  if supports_persistence:
    test_run = context.store.create_automation_test_run(
      project_id,
      user,
      operation=operation if operation in {"generation", "update"} else "generation",
      scope=scope if scope in {"full", "targeted"} else "full",
      chat_session_id=chat_session_id,
      generation_run_id=generation_run_id,
      agent_run_id=agent_run_id,
      project_version_id=project_version_id,
      changed_paths=changed_paths,
      affected_routes=affected_routes,
      test_scope={"routes": affected_routes, "changed_paths": changed_paths, "router_mode": router_mode},
    )

  run_browser_preview_qa_fn = _compatibility_export("run_browser_preview_qa", run_browser_preview_qa)
  route_results: list[dict[str, Any]] = []
  for route_index, affected_route in enumerate(affected_routes):
    screenshot_output_dir = None
    if test_run is not None:
      try:
        from ...visual_qa.artifacts import screenshot_run_directory
      except ImportError:
        from visual_qa.artifacts import screenshot_run_directory
      screenshot_output_dir = screenshot_run_directory(
        context.settings,
        project_id=project_id,
        chat_session_id=chat_session_id,
        test_run_id=str(test_run["id"]),
        phase=phase if phase in {"after", "baseline"} else "after",
        route=affected_route,
      )
    route_result = run_browser_preview_qa_fn(
      settings=context.settings,
      project_id=project_id,
      preview_url=preview_url_for_test_route(preview_url or "", affected_route, router_mode=router_mode),
      screenshot_output_dir=screenshot_output_dir,
      route=affected_route,
      interaction_prompt=interaction_prompt if route_index == 0 else "",
    )
    route_results.append({**route_result, "route": affected_route})
    if route_result.get("status") == "failed":
      break
  browser_result = merge_route_visual_qa_results(route_results)
  automation_test = None
  if test_run is not None:
    try:
      from ...visual_qa.persistence import persist_visual_qa_result
    except ImportError:
      from visual_qa.persistence import persist_visual_qa_result
    automation_test = persist_visual_qa_result(
      store=context.store,
      user=user,
      test_run=test_run,
      browser_result=browser_result,
      project_id=project_id,
      chat_session_id=chat_session_id,
      project_version_id=project_version_id,
      phase=phase if phase in {"after", "baseline"} else "after",
    )
  browser_checks = [item for item in browser_result.get("checks", []) if isinstance(item, dict)]
  browser_warnings = [item for item in browser_result.get("warnings", []) if isinstance(item, str)]
  browser_status = str(browser_result.get("status") or "unknown")
  interaction_required = prompt_requires_interaction_qa(interaction_prompt)
  interaction_result = (
    browser_result.get("interaction")
    if isinstance(browser_result.get("interaction"), dict)
    else None
  )
  layout_issues = [item for item in browser_result.get("layout_issues", []) if isinstance(item, dict)]
  layout_severity = str(browser_result.get("severity") or "unknown")
  if layout_severity == "high":
    checks.append(
      {
        "name": "layout_qa",
        "status": "failed",
        "detail": f"{len(layout_issues)} high-severity layout issue(s) detected.",
      }
    )
    warnings.append("Preview layout QA failed: high severity layout issues were detected.")
    return {
      "project_id": project_id,
      "status": "failed",
      "mode": "layout_qa_failed",
      "browser_rendered": bool(browser_result.get("browser_rendered")),
      "checks": checks + browser_checks,
      "warnings": warnings + browser_warnings,
      "browser": {
        "status": browser_status,
        "mode": browser_result.get("mode"),
        "target_url": browser_result.get("target_url"),
        "browser_command": browser_result.get("browser_command"),
        "browser_command_source": browser_result.get("browser_command_source"),
        "failure_kind": browser_result.get("failure_kind"),
      },
      "layout_checked": bool(browser_result.get("layout_checked")),
      "viewport_results": [item for item in browser_result.get("viewport_results", []) if isinstance(item, dict)],
      "layout_issues": layout_issues,
      "severity": layout_severity,
      "automation_test": automation_test,
    }
  if interaction_required and (
    browser_status != "passed"
    or not interaction_result
    or interaction_result.get("status") != "passed"
  ):
    return {
      "project_id": project_id,
      "status": "failed",
      "mode": "interaction_qa_failed",
      "browser_rendered": bool(browser_result.get("browser_rendered")),
      "checks": checks + browser_checks,
      "warnings": warnings + browser_warnings + (
        ["The requested control could not be verified in a rendered browser."]
        if not interaction_result
        else []
      ),
      "browser": {
        "status": browser_status,
        "mode": browser_result.get("mode"),
        "target_url": browser_result.get("target_url"),
        "failure_kind": browser_result.get("failure_kind") or "interaction_qa_unavailable",
      },
      "interaction": interaction_result,
      "layout_checked": bool(browser_result.get("layout_checked")),
      "viewport_results": [
        item for item in browser_result.get("viewport_results", []) if isinstance(item, dict)
      ],
      "layout_issues": layout_issues,
      "severity": layout_severity,
      "automation_test": automation_test,
    }
  if browser_status != "passed":
    if browser_result.get("failure_kind") == "runtime_error":
      reason = "; ".join(browser_warnings) or "Browser runtime QA detected an uncaught preview error."
      raise ToolExecutionError(f"Preview runtime QA failed: {reason}")
    checks.append(
      {
        "name": "browser_render_nonblocking",
        "status": "warning",
        "detail": "Browser render QA did not pass, but the staged Vite preview build is ready.",
      }
    )
    warnings.append(
      "Browser-render QA did not pass; continuing because preview build integrity passed."
    )

  return {
    "project_id": project_id,
    "status": "passed",
    "mode": browser_result.get("mode") if browser_status == "passed" else "backend_preview_integrity",
    "browser_rendered": bool(browser_result.get("browser_rendered")),
    "checks": checks + browser_checks,
    "warnings": warnings + browser_warnings,
    "browser": {
      "status": browser_status,
      "mode": browser_result.get("mode"),
      "target_url": browser_result.get("target_url"),
      "browser_command": browser_result.get("browser_command"),
      "browser_command_source": browser_result.get("browser_command_source"),
      "failure_kind": browser_result.get("failure_kind"),
    },
    "layout_checked": bool(browser_result.get("layout_checked")),
    "viewport_results": [item for item in browser_result.get("viewport_results", []) if isinstance(item, dict)],
    "layout_issues": layout_issues,
    "severity": layout_severity,
    "interaction": browser_result.get("interaction"),
    "automation_test": automation_test,
  }


def sync_local_project_tool(context: ToolRuntimeContext, user: UserContext, arguments: dict[str, Any]) -> dict[str, Any]:
  project_id = required_string(arguments, "project_id")
  direction = required_string(arguments, "direction").lower()
  if direction not in {"pull", "push"}:
    raise ToolExecutionError("direction must be pull or push.")
  project = context.store.get_project(project_id, user)
  if not project:
    raise ToolExecutionError("Project not found.")
  local_path = project.get("local_path")
  if not isinstance(local_path, str) or not local_path.strip():
    raise ToolExecutionError("Project is not linked to a local folder.")
  local_root = resolve_local_project_path(context.settings, local_path)

  if direction == "pull":
    files = read_local_project_files(local_root)
    context.store.replace_project_files(
      project_id,
      user,
      files,
      event_type="local.pulled",
      event_payload={"path": str(local_root), "source": "tool_registry"},
      allow_prune_missing=True,
    )
    invalidate_project_files_snapshot(context, user, project_id)
    return {"project_id": project_id, "direction": "pull", "path": str(local_root), "file_count": len(files)}

  files = snapshot_project_files(context, user, project_id)
  allow_prune_missing = bool(arguments.get("allow_prune_missing"))
  count = write_local_project_files(
    local_root,
    files,
    prune_missing=allow_prune_missing,
    allow_prune_missing=allow_prune_missing,
  )
  add_store_event_if_supported(
    context,
    project_id,
    user,
    "local.pushed",
    {"path": str(local_root), "count": count, "source": "tool_registry", "mode": "replace_all" if allow_prune_missing else "upsert"},
  )
  return {
    "project_id": project_id,
    "direction": "push",
    "path": str(local_root),
    "file_count": count,
    "mode": "replace_all" if allow_prune_missing else "upsert",
  }
