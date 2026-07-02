from __future__ import annotations

from typing import Any, Callable

try:
  from ...storage import UserContext
except ImportError:
  from storage import UserContext

try:
  from .commit_policy import VISUAL_QA_FAILED_FILES_COMMITTED_MESSAGE
except ImportError:
  from agents.streaming.commit_policy import VISUAL_QA_FAILED_FILES_COMMITTED_MESSAGE

ProgressCallback = Callable[..., None]


def run_precommit_automation_gate(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  candidate_files: list[dict[str, Any]],
  changed_paths: list[str],
  operation: str,
  prompt: str,
  chat_session_id: str | None,
  agent_run_id: str | None,
  emit_progress: ProgressCallback,
  skip_visual_qa: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
  try:
    from ...agentic.tools.handlers import build_staged_project_preview_tool, run_preview_visual_qa_tool
    from ...visual_qa import build_automated_test_scope
  except ImportError:
    from agentic.tools.handlers import build_staged_project_preview_tool, run_preview_visual_qa_tool
    from visual_qa import build_automated_test_scope

  try:
    from .build_gate import normalize_files_before_build
  except ImportError:
    from agents.streaming.build_gate import normalize_files_before_build
  normalized_candidates, normalization_paths = normalize_files_before_build(candidate_files)
  effective_changed_paths = list(dict.fromkeys([*changed_paths, *normalization_paths]))
  test_scope = build_automated_test_scope(
    normalized_candidates,
    changed_paths=effective_changed_paths,
    operation=operation,
    prompt=prompt,
  )
  emit_progress(
    "automation.precommit.started",
    "Building and screenshot-testing staged candidate files before commit",
    status="running",
    detail={"scope": test_scope},
  )
  preview_result = build_staged_project_preview_tool(
    tool_context,
    user,
    {"project_id": project_id, "files": normalized_candidates},
  )
  version = preview_result.get("version") if isinstance(preview_result.get("version"), dict) else {}
  build_result = {
    "status": str(version.get("status") or "failed"),
    "preview_url": version.get("preview_url"),
    "version_id": version.get("id"),
    "build_log": version.get("build_log"),
    "precommit": True,
    "candidate_files": normalized_candidates,
    "normalization_paths": normalization_paths,
  }
  if build_result["status"] != "ready":
    emit_progress(
      "automation.precommit.failed",
      "Staged candidate build failed; project files were not committed",
      status="failed",
      detail={"build_result": build_result, "files_committed": False},
    )
    return build_result, None

  if skip_visual_qa:
    emit_progress(
      "automation.precommit.passed",
      "Staged candidate build passed (visual QA skipped for cosmetic style update)",
      status="completed",
      detail={"build_result": build_result, "files_committed": True, "visual_qa_skipped": True},
    )
    return build_result, {"status": "passed", "skipped": True}

  visual_result = run_preview_visual_qa_tool(
    tool_context,
    user,
    {
      "project_id": project_id,
      "status": "ready",
      "preview_url": str(version.get("preview_url") or ""),
      "build_log": str(version.get("build_log") or ""),
      "operation": "update" if operation == "update" else "generation",
      "scope": str(test_scope.get("scope") or "full"),
      "phase": "after",
      "chat_session_id": chat_session_id or "",
      "agent_run_id": agent_run_id or "",
      "project_version_id": str(version.get("id") or ""),
      "route": str((test_scope.get("affected_routes") or ["/"])[0]),
      "changed_paths": list(test_scope.get("changed_paths") or []),
      "affected_routes": list(test_scope.get("affected_routes") or ["/"]),
      "router_mode": str(test_scope.get("router_mode") or "hash"),
    },
  )
  passed = str(visual_result.get("status") or "") == "passed"
  emit_progress(
    "automation.precommit.passed" if passed else "automation.precommit.failed",
    (
      "Staged candidate automated testing passed"
      if passed
      else "Staged candidate visual testing failed; project files were not committed"
    ),
    status="completed" if passed else "failed",
    detail={
      "build_result": build_result,
      "automation_test": visual_result.get("automation_test"),
      "files_committed": False,
    },
  )
  return build_result, visual_result


def post_update_visual_qa_enabled() -> bool:
  try:
    from ..runtime_config import post_update_visual_qa_enabled as _enabled
  except ImportError:
    from agents.runtime_config import post_update_visual_qa_enabled as _enabled
  return _enabled()


def run_post_update_visual_qa(
  *,
  project_id: str,
  user: UserContext,
  tool_context: Any,
  build_gate_result: dict[str, Any] | None,
  emit_progress: ProgressCallback,
  changed_paths: list[str] | None = None,
  chat_session_id: str | None = None,
  agent_run_id: str | None = None,
  prompt: str = "",
  operation: str = "update",
) -> dict[str, Any] | None:
  if not post_update_visual_qa_enabled():
    return None
  if not isinstance(build_gate_result, dict):
    return None
  if str(build_gate_result.get("status") or "").lower() != "ready":
    return None

  emit_progress(
    "gate.visual_qa.running",
    "Running post-update visual QA on staged preview",
    status="running",
    detail={
      "preview_url": build_gate_result.get("preview_url"),
      "version_id": build_gate_result.get("version_id"),
    },
  )

  try:
    try:
      from ...agentic.tools.handlers import run_preview_visual_qa_tool
    except ImportError:
      from agentic.tools.handlers import run_preview_visual_qa_tool

    try:
      from ...visual_qa import build_automated_test_scope
    except ImportError:
      from visual_qa import build_automated_test_scope
    project_files = (
      tool_context.store.list_files(project_id, user)
      if hasattr(tool_context, "store") and hasattr(tool_context.store, "list_files")
      else []
    )
    test_scope = build_automated_test_scope(
      project_files,
      changed_paths=list(changed_paths or []),
      operation=operation,
      prompt=prompt,
    )
    result = run_preview_visual_qa_tool(
      tool_context,
      user,
      {
        "project_id": project_id,
        "status": "ready",
        "preview_url": str(build_gate_result.get("preview_url") or ""),
        "build_log": str(build_gate_result.get("build_log") or ""),
        "operation": "update" if operation == "update" else "generation",
        "scope": str(test_scope.get("scope") or "targeted"),
        "chat_session_id": chat_session_id or "",
        "agent_run_id": agent_run_id or "",
        "project_version_id": str(build_gate_result.get("version_id") or ""),
        "route": str((test_scope.get("affected_routes") or ["/"])[0]),
        "changed_paths": list(test_scope.get("changed_paths") or []),
        "affected_routes": list(test_scope.get("affected_routes") or ["/"]),
        "router_mode": str(test_scope.get("router_mode") or "hash"),
      },
    )
  except Exception as exc:
    emit_progress(
      "gate.visual_qa.failed",
      f"Visual QA failed: {exc}",
      status="failed",
      detail={
        "error": str(exc),
        "category": "visual_qa",
        "code": "visual_qa_failed",
        "user_message": VISUAL_QA_FAILED_FILES_COMMITTED_MESSAGE,
        "files_committed": True,
        "suggested_actions": [
          "Open the preview and describe what looks wrong.",
          "Ask the agent to fix layout, styling, or missing sections.",
        ],
      },
    )
    return {"status": "failed", "error": str(exc)}

  status = str(result.get("status") or "unknown")
  if status == "passed":
    emit_progress(
      "gate.visual_qa.passed",
      "Post-update visual QA passed",
      status="completed",
      detail={
        "mode": result.get("mode"),
        "browser_rendered": result.get("browser_rendered"),
        "warnings": result.get("warnings") or [],
      },
    )
  else:
    emit_progress(
      "gate.visual_qa.failed",
      "Post-update visual QA did not pass",
      status="failed",
      detail={
        "status": status,
        "warnings": result.get("warnings") or [],
        "category": "visual_qa",
        "code": "visual_qa_failed",
        "user_message": VISUAL_QA_FAILED_FILES_COMMITTED_MESSAGE,
        "files_committed": True,
        "suggested_actions": [
          "Open the preview and describe what looks wrong.",
          "Ask the agent to fix layout, styling, or missing sections.",
        ],
      },
    )
  return result
