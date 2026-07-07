from __future__ import annotations

from typing import Any, Callable

from .impact import build_automated_test_scope
from .layout import DEFAULT_LAYOUT_VIEWPORTS


ProgressCallback = Callable[..., None]


def ensure_update_visual_baseline(
  *,
  project_id: str,
  user: Any,
  tool_context: Any,
  prompt: str,
  chat_session_id: str | None,
  agent_run_id: str | None,
  emit_progress: ProgressCallback,
) -> dict[str, Any] | None:
  store = getattr(tool_context, "store", None)
  if not store or not all(
    hasattr(store, name)
    for name in (
      "list_files",
      "latest_baseline_screenshot",
      "create_automation_test_run",
      "create_version",
    )
  ):
    return None
  files = store.list_files(project_id, user)
  if not files:
    return None
  scope = build_automated_test_scope(
    files,
    changed_paths=[str(item.get("path") or "") for item in files if isinstance(item, dict)],
    operation="generation",
    prompt=prompt,
  )
  routes = list(scope.get("affected_routes") or ["/"])
  missing = [
    (route, viewport["name"])
    for route in routes
    for viewport in DEFAULT_LAYOUT_VIEWPORTS
    if not store.latest_baseline_screenshot(
      project_id,
      user,
      route=route,
      viewport_name=str(viewport["name"]),
    )
  ]
  if not missing:
    return {"status": "available", "captured": False, "routes": routes}

  emit_progress(
    "automation.baseline.started",
    "Capturing current project screenshots before applying the update",
    status="running",
    detail={"routes": routes, "missing_baselines": len(missing)},
  )
  try:
    try:
      from ..agentic.tools.handlers import build_staged_project_preview_tool, run_preview_visual_qa_tool
    except ImportError:
      from agentic.tools.handlers import build_staged_project_preview_tool, run_preview_visual_qa_tool
    preview_result = build_staged_project_preview_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": files},
    )
    version = preview_result.get("version") if isinstance(preview_result.get("version"), dict) else {}
    if str(version.get("status") or "") != "ready":
      raise RuntimeError("Current project could not be built for before-update screenshots.")
    result = run_preview_visual_qa_tool(
      tool_context,
      user,
      {
        "project_id": project_id,
        "status": "ready",
        "preview_url": str(version.get("preview_url") or ""),
        "build_log": str(version.get("build_log") or ""),
        "operation": "update",
        "scope": "full",
        "phase": "baseline",
        "chat_session_id": chat_session_id or "",
        "agent_run_id": agent_run_id or "",
        "project_version_id": str(version.get("id") or ""),
        "route": routes[0],
        "affected_routes": routes,
        "router_mode": str(scope.get("router_mode") or "hash"),
      },
    )
    emit_progress(
      "automation.baseline.completed",
      "Captured before-update screenshot baseline",
      status="completed",
      detail={"routes": routes, "automation_test": result.get("automation_test")},
    )
    return {"status": result.get("status"), "captured": True, "routes": routes}
  except Exception as exc:
    emit_progress(
      "automation.baseline.failed",
      f"Before-update screenshot baseline could not be captured: {exc}",
      status="failed",
      detail={"error": str(exc), "routes": routes},
    )
    return {"status": "failed", "captured": False, "routes": routes, "error": str(exc)}
