from __future__ import annotations

from typing import Any

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from .errors import TargetedUpdateNoMatchError
from .file_ops import merge_project_file_changes, project_files_to_tool_files, tool_files_to_artifact_files
from .state import append_step
from .targeted_updates import (
  apply_targeted_file_update,
  build_project_file_keyword_index,
  infer_project_title_from_files,
  targeted_update_goal,
  targeted_update_label,
  targeted_update_review,
  targeted_update_workflow_plan,
)
from .update_analysis import targeted_update_request_from_analysis
from .values import object_value, text_or_default


def apply_targeted_update_shortcut(state: dict[str, Any], *, project_id: str) -> bool:
  if text_or_default(state.get("operation"), "generate") != "update":
    return False
  previous_files = project_files_to_tool_files(object_value(state.get("read_result")).get("files"))
  if not previous_files:
    return False
  update_analysis = object_value(state.get("update_analysis"))
  request = targeted_update_request_from_analysis(update_analysis)
  if not request:
    return False
  file_index = build_project_file_keyword_index(previous_files)
  changed_files = apply_targeted_file_update(previous_files, request)
  if not changed_files:
    no_match = {
      "status": "no_match",
      "kind": request["kind"],
      "requested_value": request.get("new_value") or request.get("palette_label"),
      "reason": "No high-confidence existing file location matched this simple update request. Full regeneration was blocked to preserve the current website.",
      "file_index": file_index,
      "project_id": project_id,
    }
    state["targeted_update_no_match"] = no_match
    append_step(
      state,
      "Targeted Update Agent",
      "targeted_update_no_match",
      {"prompt": state.get("prompt"), "kind": request["kind"]},
      no_match,
    )
    log_query_event(
      "targeted_update.no_match",
      status="failed",
      payload={
        "kind": request["kind"],
        "requested_value": request.get("new_value") or request.get("palette_label"),
        "indexed_file_count": len(file_index),
        "skipped_dynamic_agents": True,
      },
    )
    raise TargetedUpdateNoMatchError(
      "Targeted update could not be applied safely: no high-confidence brand/title/CTA location was found. "
      "Full regeneration was blocked to preserve the existing website."
    )

  changed_paths = [file_item["path"] for file_item in changed_files]
  candidate_files = merge_project_file_changes(previous_files, changed_files)
  title = infer_project_title_from_files(previous_files) or "Updated Website"
  update_label = targeted_update_label(request)
  update_goal = targeted_update_goal(request)
  generated_website = {
    "title": title,
    "headline": f"{title} targeted update applied",
    "subheadline": f"{update_goal} Existing layout, modules, and unrelated content were preserved.",
    "primary_cta": "View preview",
    "secondary_cta": "Review changes",
    "preview_html": "",
    "theme": {
      "colors": {
        "primary": request["primary_hex"],
        "secondary": request["secondary_hex"],
        "accent": "#111827",
        "background": request["background_hex"],
        "text": "#111827",
      },
      "style_direction": f"Targeted {update_label}",
    },
    "sections": [
      {
        "name": "Targeted update",
        "purpose": "Preserve the existing website and update only the requested simple fields.",
        "content": f"Updated {update_label} in {', '.join(changed_paths)}.",
        "items": ["Existing layout preserved", "Unrelated code preserved", "Preview validation required before commit"],
      }
    ],
    "files": tool_files_to_artifact_files(candidate_files, changed_file_paths=changed_paths),
  }
  state["brief"] = {
    "operation": "update",
    "business_type": "Existing website",
    "audience": "Existing website visitors",
    "goal": text_or_default(state.get("prompt"), "Update website"),
    "style": generated_website["theme"]["style_direction"],
    "required_sections": ["Targeted update"],
    "missing_information": [],
    "update_goal": state.get("prompt"),
    "likely_files_to_change": changed_paths,
    "targeted_update_shortcut": True,
  }
  state["dynamic_workflow_plan"] = targeted_update_workflow_plan(request, changed_paths)
  state["dynamic_specialist_results"] = {
    "status": "skipped",
    "reason": "Model selected a simple targeted update; Python applied the validated patch without full regeneration.",
    "results": {},
    "candidate_changes": [],
    "rejected_candidate_changes": [],
  }
  state["dynamic_specialists_completed"] = True
  state["plan"] = {
    "operation": "update",
    "sections": ["Targeted update"],
    "layout_strategy": "Patch existing project files only; preserve current layout and modules.",
    "interactions": ["No interaction changes requested"],
    "quality_checks": ["Artifact validates", "Staged preview builds", "Runtime QA passes"],
    "update_strategy": f"Apply {update_label} to high-confidence existing file locations only.",
    "files_to_change": changed_paths,
    "preserve_rules": ["Do not regenerate unrelated website content.", "Do not replace the existing layout."],
    "targeted_update_shortcut": True,
  }
  state["ux_review"] = targeted_update_review("ux_review_agent")
  state["accessibility_review"] = targeted_update_review("accessibility_review_agent")
  state["artifact_response"] = {"generated_website": generated_website, "implementation_notes": {"self_checks": ["Targeted update shortcut applied."]}}
  state["generated_website"] = generated_website
  state["files"] = generated_website["files"]
  state["candidate_files"] = candidate_files
  state["changed_file_paths"] = changed_paths
  state["dynamic_patch_integrated"] = True
  state["candidate_change_summary"] = {
    "accepted_count": 0,
    "rejected_count": 0,
    "accepted": [],
    "rejected": [],
    "integration_status": "skipped",
    "integration_reason": "No dynamic-agent patch was needed for a model-selected targeted update.",
  }
  state["targeted_update"] = {
    "status": "applied",
    "kind": request["kind"],
    "label": update_label,
    "changed_file_paths": changed_paths,
    "file_index": file_index,
    "project_id": project_id,
    "skipped_dynamic_agents": True,
  }
  log_query_event(
    "targeted_update.applied",
    payload={
      "kind": request["kind"],
      "label": update_label,
      "changed_file_paths": changed_paths,
      "indexed_file_count": len(file_index),
      "skipped_dynamic_agents": True,
    },
  )
  return True
