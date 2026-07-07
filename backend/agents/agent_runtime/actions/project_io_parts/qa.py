from __future__ import annotations

from typing import Any

from ...progress import emit_runtime_progress
from ...repair_tracking import record_repair_error
from ...state import append_step
from ...tooling import execute_tool_call
from ...values import list_value, object_value, text_or_default
from ..context import RuntimeActionContext
from .parts import interaction_fix_verification_reason, small_scoped_update_static_qa_reason, visual_qa_failure_reason


def handle_run_preview_visual_qa(ctx: RuntimeActionContext) -> None:
  state = ctx.state
  agent = ctx.agent
  tool_executor = ctx.tool_executor
  tool_context = ctx.tool_context
  user = ctx.user
  project_id = ctx.project_id
  progress = ctx.progress

  from backend.visual_qa import build_automated_test_scope

  candidate_files = [item for item in list_value(state.get("candidate_files")) if isinstance(item, dict)]
  test_scope = build_automated_test_scope(
    candidate_files,
    changed_paths=[str(path) for path in list_value(state.get("changed_file_paths")) if str(path).strip()],
    operation=text_or_default(state.get("operation"), "generate"),
    prompt=text_or_default(state.get("prompt"), ""),
  )
  state["automated_test_scope"] = test_scope

  interaction_reason = interaction_fix_verification_reason(state)
  if interaction_reason:
    visual_qa_result = {"status": "failed", "mode": "static_interaction_verification", "warnings": [interaction_reason]}
    state["visual_qa_result"] = visual_qa_result
    record_repair_error(state, interaction_reason, source="visual_qa")
    append_step(
      state,
      agent,
      "verify_requested_interaction_fix",
      {"project_id": project_id, "changed_file_paths": list(state.get("changed_file_paths") or [])},
      visual_qa_result,
    )
    return

  static_skip_reason = small_scoped_update_static_qa_reason(state) if not test_scope.get("visual_expected") else ""
  if static_skip_reason:
    visual_qa_result = {
      "status": "passed",
      "mode": "static_fast_scoped_update_qa",
      "browser_rendered": False,
      "checks": [
        {"name": "vite_build", "status": "passed", "detail": "Staged preview build completed before commit."},
        {"name": "scope", "status": "passed", "detail": static_skip_reason},
      ],
      "warnings": [],
    }
    state["visual_qa_result"] = visual_qa_result
    append_step(
      state,
      agent,
      "run_static_fast_scoped_update_qa",
      {"project_id": project_id, "changed_file_paths": list(state.get("changed_file_paths") or [])},
      visual_qa_result,
    )
    return

  preview = object_value(state.get("preview"))
  emit_runtime_progress(
    progress,
    "gate.visual_qa.running",
    "Running preview visual QA on staged build",
    status="running",
    detail={"preview_status": preview.get("status"), "preview_url": preview.get("preview_url")},
  )
  visual_qa_result = execute_tool_call(
    state,
    tool_executor=tool_executor,
    tool_context=tool_context,
    user=user,
    agent=agent,
    name="RUN_PREVIEW_VISUAL_QA",
    arguments={
      "project_id": project_id,
      "status": text_or_default(preview.get("status"), "unknown"),
      "preview_url": text_or_default(preview.get("preview_url"), ""),
      "build_log": text_or_default(preview.get("build_log"), ""),
      "operation": "update" if text_or_default(state.get("operation"), "generate") == "update" else "generation",
      "scope": text_or_default(test_scope.get("scope"), "full"),
      "chat_session_id": text_or_default(state.get("chat_session_id"), ""),
      "agent_run_id": text_or_default(state.get("agent_run_id"), ""),
      "project_version_id": text_or_default(preview.get("id") or preview.get("version_id"), ""),
      "route": text_or_default(list_value(test_scope.get("affected_routes"))[0] if list_value(test_scope.get("affected_routes")) else "/", "/"),
      "changed_paths": list_value(test_scope.get("changed_paths")),
      "affected_routes": list_value(test_scope.get("affected_routes")),
      "router_mode": text_or_default(test_scope.get("router_mode"), "hash"),
    },
  )
  state["visual_qa_result"] = visual_qa_result
  if object_value(visual_qa_result).get("status") != "passed":
    warnings = visual_qa_result.get("warnings") if isinstance(visual_qa_result, dict) else None
    reason = visual_qa_failure_reason(visual_qa_result, warnings)
    record_repair_error(state, reason or "Preview visual QA did not pass.", source="visual_qa")
    emit_runtime_progress(
      progress,
      "gate.visual_qa.failed",
      reason or "Preview visual QA did not pass",
      status="failed",
      detail={
        "status": object_value(visual_qa_result).get("status"),
        "warnings": warnings or [],
        "layout_checked": object_value(visual_qa_result).get("layout_checked"),
        "layout_severity": object_value(visual_qa_result).get("severity"),
        "category": "visual_qa",
        "code": "visual_qa_failed",
        "user_message": "Staged preview visual QA failed. No generated files were committed.",
        "suggested_actions": [
          "Open the preview and describe what looks wrong.",
          "Ask the agent to fix layout, styling, or missing sections.",
        ],
      },
    )
  else:
    emit_runtime_progress(
      progress,
      "gate.visual_qa.passed",
      "Preview visual QA passed",
      status="completed",
      detail={
        "mode": visual_qa_result.get("mode") if isinstance(visual_qa_result, dict) else None,
        "browser_rendered": visual_qa_result.get("browser_rendered") if isinstance(visual_qa_result, dict) else False,
      },
    )
  append_step(
    state,
    agent,
    "run_preview_visual_qa",
    {"project_id": project_id, "preview_status": preview.get("status")},
    visual_qa_result,
    tool_calls=["RUN_PREVIEW_VISUAL_QA"],
  )
