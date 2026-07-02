"""LangGraph parity hooks for the default streaming / parallel worker path (MT-6)."""

from __future__ import annotations

from typing import Any, Callable

try:
  from ..patch_approval.gate import emit_patch_approval_required, patch_approval_active
  from ..patch_approval.presentation import public_patch_approval_brief
  from ..patch_approval.storage import persist_pending_patch
except ImportError:
  from agents.patch_approval.gate import emit_patch_approval_required, patch_approval_active
  from agents.patch_approval.presentation import public_patch_approval_brief
  from agents.patch_approval.storage import persist_pending_patch

ProgressCallback = Callable[..., None]


def clarification_stream_result(question: str) -> dict[str, Any]:
  """Return a streaming runtime result that asks the user for clarification."""
  message = str(question or "").strip() or "Please clarify what you want to change."
  return {
    "generated_website": {
      "title": "Clarification needed",
      "headline": "Clarification needed",
      "subheadline": message,
      "primary_cta": "Reply in chat",
      "secondary_cta": "Cancel",
      "preview_html": "",
      "theme": {
        "colors": {
          "primary": "#0f766e",
          "secondary": "#2563eb",
          "accent": "#14212b",
          "background": "#ffffff",
          "text": "#14212b",
        },
        "style_direction": "Clarification response",
      },
      "sections": [
        {
          "name": "Clarification",
          "purpose": "Collect missing update details before changing files.",
          "content": message,
          "items": [],
        }
      ],
      "files": [],
    },
    "artifact_response": {"summary": message, "clarification_question": message},
    "runtime": {
      "engine": "update_clarification",
      "status": "needs_clarification",
      "output_text": message,
      "clarification_question": message,
    },
  }


def streaming_path_parity_enabled() -> bool:
  try:
    from ..runtime_config import streaming_path_parity_enabled as _enabled
  except ImportError:
    from agents.runtime_config import streaming_path_parity_enabled as _enabled
  return _enabled()


def _build_project_diff(before_files: list[dict[str, str]], after_files: list[dict[str, str]]) -> dict[str, Any]:
  try:
    from ...code_diff import build_project_diff
  except ImportError:
    from code_diff import build_project_diff
  return build_project_diff(before_files, after_files, compare_mode="changed_only")


def streaming_patch_approval_gate(
  *,
  tool_context: Any,
  user: Any,
  project_id: str,
  prompt: str,
  write_payload: list[dict[str, str]],
  files_before_map: dict[str, str],
  emit_progress: ProgressCallback,
  patch_action: str | None = None,
  summary: str = "",
) -> dict[str, Any] | None:
  """Pause streaming commit when patch approval is enabled. Returns a full runtime_result or None."""
  if not streaming_path_parity_enabled():
    return None
  if not patch_approval_active(tool_context):
    return None
  if patch_action == "approve":
    return None
  if not write_payload:
    return None

  changed_paths = sorted({str(item.get("path") or "") for item in write_payload if item.get("path")})
  before_files = [{"path": path, "content": files_before_map.get(path, "")} for path in changed_paths]
  after_files = [{"path": str(item.get("path") or ""), "content": str(item.get("content") or "")} for item in write_payload]
  diff_payload = _build_project_diff(before_files, after_files)
  if diff_payload.get("file_count"):
    emit_progress(
      "patch.proposed",
      f"Proposed patch: {diff_payload.get('file_count', len(write_payload))} file(s)",
      status="running",
      detail=diff_payload,
    )

  snapshot = {
    "prompt": str(prompt or ""),
    "operation": "update",
    "paths": changed_paths,
    "candidate_files": after_files,
    "diff_detail": diff_payload,
  }
  pending = persist_pending_patch(tool_context, user, project_id=project_id, snapshot=snapshot)
  emit_patch_approval_required(emit_progress, pending)

  try:
    from .file_agent import _build_generated_website
  except ImportError:
    from agents.streaming.file_agent import _build_generated_website

  generated_website = _build_generated_website(
    write_payload,
    summary=summary or "Proposed patch is waiting for your approval.",
  )
  runtime = {
    "engine": "streaming_patch_approval",
    "status": "awaiting_patch_approval",
    "awaiting_patch_approval": True,
    "patch_approval": public_patch_approval_brief(pending),
    "changed_paths": changed_paths,
    "output_text": summary or "Waiting for patch approval before applying changes.",
  }
  return {
    "generated_website": generated_website,
    "artifact_response": {
      "summary": summary or "Waiting for patch approval.",
      "files": write_payload,
      "patch_approval": public_patch_approval_brief(pending),
    },
    "runtime": runtime,
    "awaiting_patch_approval": True,
    "patch_approval": pending,
  }


def run_streaming_post_commit_gates(
  *,
  project_id: str,
  user: Any,
  tool_context: Any,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  changed_paths: list[str],
  files_before_map: dict[str, str] | None = None,
  persist_reason: str = "streaming_commit",
  chat_session_id: str | None = None,
  agent_run_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
  """Run build gate + visual QA after commit. Optionally rollback on hard build failure."""
  if not changed_paths:
    return None, None
  if intent != "website_update":
    return None, None
  if not streaming_path_parity_enabled():
    return None, None

  build_gate_result: dict[str, Any] | None = None
  visual_qa_result: dict[str, Any] | None = None
  try:
    from .build_gate import post_update_build_gate_enabled, run_post_update_build_gate
  except ImportError:
    from agents.streaming.build_gate import post_update_build_gate_enabled, run_post_update_build_gate

  if not post_update_build_gate_enabled():
    return None, None

  try:
    from .commit_policy import should_rollback_after_build_gate
  except ImportError:
    from agents.streaming.commit_policy import should_rollback_after_build_gate

  build_gate_result = run_post_update_build_gate(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    intent=intent,
    artifact_provider=artifact_provider,
    emit_progress=emit_progress,
    changed_paths=changed_paths,
  )

  status = str(build_gate_result.get("status") or "").lower()
  if should_rollback_after_build_gate(build_gate_result) and files_before_map:
    _rollback_changed_paths(
      tool_context=tool_context,
      user=user,
      project_id=project_id,
      changed_paths=changed_paths,
      files_before_map=files_before_map,
      emit_progress=emit_progress,
      build_gate_result=build_gate_result,
      persist_reason=persist_reason,
    )

  if status == "ready":
    try:
      from .streaming_visual_qa import run_post_update_visual_qa
    except ImportError:
      from agents.streaming.streaming_visual_qa import run_post_update_visual_qa
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
      operation="update",
    )

  return build_gate_result, visual_qa_result


def _rollback_changed_paths(
  *,
  tool_context: Any,
  user: Any,
  project_id: str,
  changed_paths: list[str],
  files_before_map: dict[str, str],
  emit_progress: ProgressCallback,
  build_gate_result: dict[str, Any],
  persist_reason: str,
) -> None:
  restore_payload = [
    {"path": path, "content": files_before_map[path]}
    for path in changed_paths
    if path in files_before_map
  ]
  if not restore_payload:
    return
  try:
    try:
      from ...agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from agentic.tools.handlers import upsert_project_files_tool
    upsert_project_files_tool(
      tool_context,
      user,
      {
        "project_id": project_id,
        "files": restore_payload,
        "reason": f"{persist_reason}_build_gate_rollback",
      },
    )
    emit_progress(
      "gate.build.rollback",
      f"Restored {len(restore_payload)} file(s) after build gate failure",
      status="completed",
      detail={"paths": [item["path"] for item in restore_payload], "build_gate": build_gate_result},
    )
  except Exception as exc:
    emit_progress(
      "gate.build.rollback.failed",
      f"Could not rollback files after build gate failure: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": [item["path"] for item in restore_payload]},
    )


def try_deterministic_scoped_patch_streaming(
  *,
  update_analysis: dict[str, Any],
  tool_context: Any,
  user: Any,
  project_id: str,
  prompt: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  patch_action: str | None = None,
  chat_session_id: str | None = None,
  project_name: str = "",
) -> dict[str, Any] | None:
  """Apply model-selected deterministic targeted patch on the streaming fast path."""
  if not streaming_path_parity_enabled():
    return None
  if str(update_analysis.get("execution_strategy") or "") != "deterministic_patch":
    return None

  try:
    from ..agent_runtime.file_ops import merge_project_file_changes, project_files_to_tool_files
    from ..agent_runtime.targeted_updates import (
      apply_targeted_file_update,
      infer_project_title_from_files,
      targeted_update_goal,
      targeted_update_label,
    )
    from ..agent_runtime.update_analysis import targeted_update_request_from_analysis
  except ImportError:
    from agents.agent_runtime.file_ops import merge_project_file_changes, project_files_to_tool_files
    from agents.agent_runtime.targeted_updates import (
      apply_targeted_file_update,
      infer_project_title_from_files,
      targeted_update_goal,
      targeted_update_label,
    )
    from agents.agent_runtime.update_analysis import targeted_update_request_from_analysis

  request = targeted_update_request_from_analysis(update_analysis)
  if not request:
    return None

  store_files = tool_context.store.list_files(project_id, user)
  previous_files = project_files_to_tool_files(store_files)
  if not previous_files:
    return None

  files_before_map = {item["path"]: item["content"] for item in previous_files}
  changed_files = apply_targeted_file_update(previous_files, request)
  if not changed_files:
    return None

  candidate_files = merge_project_file_changes(previous_files, changed_files)
  changed_path_set = {item["path"] for item in changed_files}
  write_payload = [
    {"path": item["path"], "content": item["content"]}
    for item in candidate_files
    if item["path"] in changed_path_set
  ]
  changed_paths = sorted({item["path"] for item in changed_files})
  update_label = targeted_update_label(request)
  update_goal = targeted_update_goal(request)
  title = infer_project_title_from_files(previous_files) or "Updated Website"
  summary = f"Applied targeted {update_label}: {update_goal}"

  emit_progress(
    "agent.decision",
    f"Using deterministic scoped patch for {update_label}",
    status="completed",
    detail={
      "workflow": "deterministic_scoped_patch",
      "execution_strategy": "deterministic_patch",
      "changed_paths": changed_paths,
      "request_kind": request.get("kind"),
    },
  )

  approval_result = streaming_patch_approval_gate(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    prompt=prompt,
    write_payload=write_payload,
    files_before_map=files_before_map,
    emit_progress=emit_progress,
    patch_action=patch_action,
    summary=summary,
  )
  if approval_result is not None:
    approval_result["runtime"]["workflow"] = "deterministic_scoped_patch"
    return approval_result

  if hasattr(tool_context.store, "create_version"):
    try:
      from .streaming_visual_qa import run_precommit_automation_gate

      precommit_build, precommit_visual = run_precommit_automation_gate(
        project_id=project_id,
        user=user,
        tool_context=tool_context,
        candidate_files=candidate_files,
        changed_paths=changed_paths,
        operation="update",
        prompt=prompt,
        chat_session_id=chat_session_id,
        agent_run_id=None,
        emit_progress=emit_progress,
      )
      if (
        str(precommit_build.get("status") or "") != "ready"
        or str((precommit_visual or {}).get("status") or "") != "passed"
      ):
        return None
    except Exception as exc:
      emit_progress(
        "automation.precommit.failed",
        f"Deterministic patch pre-commit testing failed: {exc}",
        status="failed",
        detail={"error": str(exc), "files_committed": False},
      )
      return None

  try:
    try:
      from ...agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from agentic.tools.handlers import upsert_project_files_tool
    upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": write_payload, "reason": "deterministic_scoped_patch"},
    )
    emit_progress(
      "files.persisted",
      f"Saved {len(write_payload)} file(s) from deterministic scoped patch",
      status="completed",
      detail={"paths": changed_paths, "workflow": "deterministic_scoped_patch"},
    )
  except Exception as exc:
    emit_progress(
      "files.persist.failed",
      f"Deterministic scoped patch failed to persist: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": changed_paths},
    )
    return None

  build_gate_result, visual_qa_result = run_streaming_post_commit_gates(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    intent=intent,
    artifact_provider=artifact_provider,
    emit_progress=emit_progress,
    changed_paths=changed_paths,
    files_before_map=files_before_map,
    persist_reason="deterministic_scoped_patch",
    chat_session_id=chat_session_id,
  )

  try:
    from .file_agent import _build_generated_website
  except ImportError:
    from agents.streaming.file_agent import _build_generated_website

  generated_website = _build_generated_website(write_payload, summary=summary)
  runtime: dict[str, Any] = {
    "engine": "deterministic_scoped_patch",
    "workflow": "deterministic_scoped_patch",
    "changed_paths": changed_paths,
    "output_text": summary,
    "update_analysis": update_analysis,
    "targeted_update": {
      "status": "applied",
      "kind": request.get("kind"),
      "label": update_label,
      "changed_file_paths": changed_paths,
    },
  }
  if build_gate_result:
    runtime["build_gate"] = build_gate_result
    runtime["final_output"] = {
      "preview_status": build_gate_result.get("status"),
      "preview_url": build_gate_result.get("preview_url"),
    }
  if visual_qa_result:
    runtime["visual_qa"] = visual_qa_result
    runtime.setdefault("final_output", {})["visual_qa_status"] = visual_qa_result.get("status")

  _ = project_name
  return {
    "generated_website": generated_website,
    "artifact_response": {"summary": summary, "files": write_payload, "targeted_update": runtime["targeted_update"]},
    "runtime": runtime,
  }


def try_deterministic_module_contract_fix_streaming(
  *,
  prompt: str,
  tool_context: Any,
  user: Any,
  project_id: str,
  emit_progress: ProgressCallback,
  patch_action: str | None = None,
  chat_session_id: str | None = None,
  agent_run_id: str | None = None,
) -> dict[str, Any] | None:
  """Repair local default/named import mismatches before spending a model call."""
  try:
    from .module_contracts import normalize_relative_import_export_contracts
  except ImportError:
    from agents.streaming.module_contracts import normalize_relative_import_export_contracts

  previous_files = [
    {"path": str(item.get("path") or ""), "content": str(item.get("content") or "")}
    for item in tool_context.store.list_files(project_id, user)
    if isinstance(item, dict) and item.get("path")
  ]
  if not previous_files:
    return None
  candidate_files, changed_paths, repairs = normalize_relative_import_export_contracts(previous_files)
  if not changed_paths:
    return None

  files_before_map = {item["path"]: item["content"] for item in previous_files}
  candidate_map = {item["path"]: item["content"] for item in candidate_files}
  write_payload = [{"path": path, "content": candidate_map[path]} for path in changed_paths]
  summary = "Fixed incompatible default and named imports so the generated project can build."

  emit_progress(
    "error.diagnosed",
    f"Detected {len(repairs)} local import/export contract mismatch(es)",
    status="completed",
    detail={"workflow": "deterministic_module_contract_fix", "repairs": repairs, "changed_paths": changed_paths},
  )

  approval_result = streaming_patch_approval_gate(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    prompt=prompt,
    write_payload=write_payload,
    files_before_map=files_before_map,
    emit_progress=emit_progress,
    patch_action=patch_action,
    summary=summary,
  )
  if approval_result is not None:
    approval_result["runtime"]["workflow"] = "deterministic_module_contract_fix"
    return approval_result

  build_result: dict[str, Any] | None = None
  visual_result: dict[str, Any] | None = None
  if hasattr(tool_context.store, "create_version"):
    try:
      from .streaming_visual_qa import run_precommit_automation_gate

      build_result, visual_result = run_precommit_automation_gate(
        project_id=project_id,
        user=user,
        tool_context=tool_context,
        candidate_files=candidate_files,
        changed_paths=changed_paths,
        operation="update",
        prompt=prompt,
        chat_session_id=chat_session_id,
        agent_run_id=agent_run_id,
        emit_progress=emit_progress,
      )
      if str(build_result.get("status") or "") != "ready":
        return None
      if str((visual_result or {}).get("status") or "") not in {"", "passed"}:
        emit_progress(
          "automation.precommit.visual_advisory",
          "Import/export repair passed the build gate; saving the code fix and keeping visual QA as advisory.",
          status="completed",
          detail={
            "workflow": "deterministic_module_contract_fix",
            "build_status": build_result.get("status"),
            "visual_status": (visual_result or {}).get("status"),
            "changed_paths": changed_paths,
            "files_committed": True,
            "advisory": True,
          },
        )
      normalized_candidates = list(build_result.get("candidate_files") or candidate_files)
      candidate_map = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in normalized_candidates
        if isinstance(item, dict) and item.get("path")
      }
      write_payload = [
        {"path": path, "content": content}
        for path, content in sorted(candidate_map.items())
        if files_before_map.get(path) != content
      ]
      changed_paths = [item["path"] for item in write_payload]
    except Exception as exc:
      emit_progress(
        "automation.precommit.failed",
        f"Import/export repair validation failed: {exc}",
        status="failed",
        detail={"error": str(exc), "files_committed": False},
      )
      return None

  write_result: dict[str, Any] = {}
  try:
    try:
      from ...agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from agentic.tools.handlers import upsert_project_files_tool
    write_result = upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": write_payload, "reason": "deterministic_module_contract_fix"},
    )
  except Exception as exc:
    emit_progress(
      "files.persist.failed",
      f"Import/export repair could not be saved: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": changed_paths},
    )
    return None

  emit_progress(
    "files.persisted",
    f"Saved {len(write_payload)} validated import/export repair file(s)",
    status="completed",
    detail={"paths": changed_paths, "repairs": repairs},
  )
  try:
    from .file_agent import _build_generated_website
  except ImportError:
    from agents.streaming.file_agent import _build_generated_website
  runtime: dict[str, Any] = {
    "engine": "deterministic_module_contract_fix",
    "status": "completed",
    "workflow": "deterministic_module_contract_fix",
    "changed_paths": changed_paths,
    "output_text": summary,
    "tool_source_of_truth": True,
    "local_sync": write_result.get("local_sync") if isinstance(write_result.get("local_sync"), dict) else None,
    "module_contract_repairs": repairs,
    "final_output": {"preview_status": "built"},
  }
  attach_gate_results_to_runtime(
    runtime,
    build_gate_result=build_result,
    visual_qa_result=visual_result,
  )
  return {
    "generated_website": _build_generated_website(write_payload, summary=summary),
    "artifact_response": {"summary": summary, "files": write_payload},
    "runtime": runtime,
  }


def try_deterministic_undefined_reference_fix_streaming(
  *,
  prompt: str,
  tool_context: Any,
  user: Any,
  project_id: str,
  intent: str,
  artifact_provider: Any,
  emit_progress: ProgressCallback,
  update_analysis: dict[str, Any] | None = None,
  patch_action: str | None = None,
  chat_session_id: str | None = None,
  project_name: str = "",
) -> dict[str, Any] | None:
  """Apply a zero-LLM fix for undeclared JSX identifiers like showOnboarding."""
  try:
    from ..agent_runtime.file_ops import merge_project_file_changes, project_files_to_tool_files
    from ..agent_runtime.scoped_update import deterministic_undefined_reference_fix_changes
    from ..agent_runtime.update_analysis import build_update_code_search_matches
    from ..agent_runtime.error_handling import analyze_error_context
  except ImportError:
    from agents.agent_runtime.file_ops import merge_project_file_changes, project_files_to_tool_files
    from agents.agent_runtime.scoped_update import deterministic_undefined_reference_fix_changes
    from agents.agent_runtime.update_analysis import build_update_code_search_matches
    from agents.agent_runtime.error_handling import analyze_error_context

  store_files = tool_context.store.list_files(project_id, user)
  previous_files = project_files_to_tool_files(store_files)
  if not previous_files:
    return None

  candidate_files_list = list((update_analysis or {}).get("candidate_files") or [])
  analysis = dict(update_analysis or {})
  if not candidate_files_list:
    code_matches = build_update_code_search_matches(prompt, previous_files)
    diagnosis = analyze_error_context(prompt, existing_files=previous_files, code_search_matches=code_matches)
    analysis = {
      **analysis,
      "update_mode": analysis.get("update_mode") or "bug_fix",
      "summary": analysis.get("summary") or prompt,
      "candidate_files": diagnosis.get("candidate_files") or [],
      "error_diagnosis": diagnosis,
    }

  deterministic_changes = deterministic_undefined_reference_fix_changes(
    prompt=prompt,
    update_analysis=analysis,
    existing_files=previous_files,
  )
  if not deterministic_changes:
    return None

  files_before_map = {item["path"]: item["content"] for item in previous_files}
  candidate_files = merge_project_file_changes(previous_files, deterministic_changes)
  changed_path_set = {item["path"] for item in deterministic_changes}
  write_payload = [
    {"path": item["path"], "content": item["content"]}
    for item in candidate_files
    if item["path"] in changed_path_set
  ]
  changed_paths = sorted(changed_path_set)
  summary = "Applied deterministic fix for undefined reference crash."

  emit_progress(
    "agent.decision",
    f"Using deterministic undefined-reference fix for {', '.join(changed_paths)}",
    status="completed",
    detail={
      "workflow": "deterministic_undefined_reference_fix",
      "changed_paths": changed_paths,
    },
  )

  approval_result = streaming_patch_approval_gate(
    tool_context=tool_context,
    user=user,
    project_id=project_id,
    prompt=prompt,
    write_payload=write_payload,
    files_before_map=files_before_map,
    emit_progress=emit_progress,
    patch_action=patch_action,
    summary=summary,
  )
  if approval_result is not None:
    approval_result["runtime"]["workflow"] = "deterministic_undefined_reference_fix"
    return approval_result

  if hasattr(tool_context.store, "create_version"):
    try:
      from .streaming_visual_qa import run_precommit_automation_gate

      precommit_build, precommit_visual = run_precommit_automation_gate(
        project_id=project_id,
        user=user,
        tool_context=tool_context,
        candidate_files=candidate_files,
        changed_paths=changed_paths,
        operation="update",
        prompt=prompt,
        chat_session_id=chat_session_id,
        agent_run_id=None,
        emit_progress=emit_progress,
      )
      if str(precommit_build.get("status") or "") != "ready":
        return None
      if str((precommit_visual or {}).get("status") or "") not in {"", "passed"}:
        emit_progress(
          "automation.precommit.visual_advisory",
          "Undefined-reference repair passed the build gate; saving the code fix and keeping visual QA as advisory.",
          status="completed",
          detail={
            "workflow": "deterministic_undefined_reference_fix",
            "build_status": precommit_build.get("status"),
            "visual_status": (precommit_visual or {}).get("status"),
            "changed_paths": changed_paths,
            "files_committed": True,
            "advisory": True,
          },
        )
      normalized_candidates = list(precommit_build.get("candidate_files") or candidate_files)
      candidate_map = {
        str(item.get("path") or ""): str(item.get("content") or "")
        for item in normalized_candidates
        if isinstance(item, dict) and item.get("path")
      }
      write_payload = [
        {"path": path, "content": content}
        for path, content in sorted(candidate_map.items())
        if files_before_map.get(path) != content
      ]
      changed_paths = [item["path"] for item in write_payload]
    except Exception as exc:
      emit_progress(
        "automation.precommit.failed",
        f"Undefined-reference patch pre-commit testing failed: {exc}",
        status="failed",
        detail={"error": str(exc), "files_committed": False},
      )
      return None

  write_result: dict[str, Any] = {}
  try:
    try:
      from ...agentic.tools.handlers import upsert_project_files_tool
    except ImportError:
      from agentic.tools.handlers import upsert_project_files_tool
    write_result = upsert_project_files_tool(
      tool_context,
      user,
      {"project_id": project_id, "files": write_payload, "reason": "deterministic_undefined_reference_fix"},
    )
    emit_progress(
      "files.persisted",
      f"Saved {len(write_payload)} file(s) from undefined-reference fix",
      status="completed",
      detail={"paths": changed_paths, "workflow": "deterministic_undefined_reference_fix"},
    )
  except Exception as exc:
    emit_progress(
      "files.persist.failed",
      f"Undefined-reference fix failed to persist: {exc}",
      status="failed",
      detail={"error": str(exc), "paths": changed_paths},
    )
    return None

  build_gate_result, visual_qa_result = run_streaming_post_commit_gates(
    project_id=project_id,
    user=user,
    tool_context=tool_context,
    prompt=prompt,
    intent=intent,
    artifact_provider=artifact_provider,
    emit_progress=emit_progress,
    changed_paths=changed_paths,
    files_before_map=files_before_map,
    persist_reason="deterministic_undefined_reference_fix",
    chat_session_id=chat_session_id,
  )

  try:
    from .file_agent import _build_generated_website
  except ImportError:
    from agents.streaming.file_agent import _build_generated_website

  generated_website = _build_generated_website(write_payload, summary=summary)
  runtime: dict[str, Any] = {
    "engine": "deterministic_undefined_reference_fix",
    "status": "completed",
    "workflow": "deterministic_undefined_reference_fix",
    "changed_paths": changed_paths,
    "output_text": summary,
    "tool_source_of_truth": True,
    "local_sync": write_result.get("local_sync") if isinstance(write_result.get("local_sync"), dict) else None,
    "final_output": {"preview_status": "built"},
    "update_analysis": analysis,
    "deterministic_fallback": "undefined_reference_fix",
  }
  if build_gate_result:
    runtime["build_gate"] = build_gate_result
    runtime["final_output"] = {
      "preview_status": build_gate_result.get("status"),
      "preview_url": build_gate_result.get("preview_url"),
    }
  if visual_qa_result:
    runtime["visual_qa"] = visual_qa_result
    runtime.setdefault("final_output", {})["visual_qa_status"] = visual_qa_result.get("status")

  _ = chat_session_id, project_name
  return {
    "generated_website": generated_website,
    "artifact_response": {"summary": summary, "files": write_payload},
    "runtime": runtime,
  }


def attach_gate_results_to_runtime(
  runtime: dict[str, Any],
  *,
  build_gate_result: dict[str, Any] | None,
  visual_qa_result: dict[str, Any] | None,
) -> None:
  if build_gate_result:
    runtime["build_gate"] = build_gate_result
    runtime["final_output"] = {
      "preview_status": build_gate_result.get("status"),
      "preview_url": build_gate_result.get("preview_url"),
    }
  if visual_qa_result:
    runtime["visual_qa"] = visual_qa_result
    runtime.setdefault("final_output", {})["visual_qa_status"] = visual_qa_result.get("status")
