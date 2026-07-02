from __future__ import annotations

from typing import Any

from .a2a import a2a_contract_is_complete
from .constants import REQUIRED_ARTIFACT_RUNTIME_TOOLS
from .missing import (
  missing_a2a_fields,
  missing_artifact_branch_fields,
  missing_commit_fields,
  missing_gemini_native_provider_fields,
  missing_memory_fields,
  missing_preview_fields,
  missing_supervisor_fields,
)
from .runtime import runtime_tool_names
from .scoring import add_check
from .values import int_value, list_value, object_value, text_value


def add_artifact_checks(
  checks: list[dict[str, Any]],
  *,
  response: dict[str, Any],
  runtime: dict[str, Any],
  tool_setup: dict[str, Any],
  intent: str,
) -> None:
  tool_names = runtime_tool_names(runtime)
  completion_status = object_value(runtime.get("completion_status"))
  completion_proof = object_value(runtime.get("completion_proof"))
  final_output = object_value(runtime.get("final_output"))
  a2a_runtime = object_value(object_value(response.get("agent_to_agent_communication")).get("a2a_runtime"))
  handoffs = list_value(object_value(response.get("agent_to_agent_communication")).get("agentic_handoffs")) or list_value(runtime.get("handoffs"))

  add_check(
    checks,
    name="gemini_native_provider",
    passed=(
      tool_setup.get("provider") == "gemini-native-control-artifact"
      and bool(text_value(tool_setup.get("control_provider")))
      and bool(text_value(tool_setup.get("artifact_provider")))
    ),
    detail="Artifact branches must expose Gemini control/artifact provider metadata.",
    missing=missing_gemini_native_provider_fields(tool_setup),
  )
  add_check(
    checks,
    name="artifact_branch_contract",
    passed=runtime.get("tool_source_of_truth") is True
    and runtime.get("branch") == intent
    and runtime.get("operation") == ("update" if intent == "website_update" else "generate"),
    detail=f"runtime_branch={runtime.get('branch')}, operation={runtime.get('operation')}",
    missing=missing_artifact_branch_fields(runtime, intent),
  )
  add_check(
    checks,
    name="required_runtime_tools",
    passed=all(name in tool_names for name in REQUIRED_ARTIFACT_RUNTIME_TOOLS),
    detail=f"tools={', '.join(tool_names)}",
    missing=[name for name in REQUIRED_ARTIFACT_RUNTIME_TOOLS if name not in tool_names],
  )
  add_check(
    checks,
    name="staged_preview_visual_qa",
    passed=completion_status.get("staged_preview_ready") is True
    and completion_status.get("visual_qa_passed") is True
    and object_value(runtime.get("visual_qa")).get("status") == "passed",
    detail="Staged preview must be ready and browser visual QA must pass before write.",
    missing=missing_preview_fields(runtime),
  )
  add_check(
    checks,
    name="supervisor_completion_proof",
    passed=bool(list_value(runtime.get("supervisor_audit_trail"))) and completion_proof.get("satisfied") is True,
    detail="Supervisor audit trail must justify DONE with satisfied completion proof.",
    missing=missing_supervisor_fields(runtime),
  )
  add_check(
    checks,
    name="a2a_canonical_contract",
    passed=a2a_contract_is_complete(a2a_runtime, handoffs),
    detail="Every A2A message/handoff must expose sender, receiver, task, input, output, confidence, and next_action.",
    missing=missing_a2a_fields(a2a_runtime, handoffs),
  )
  add_check(
    checks,
    name="memory_persistence",
    passed=completion_status.get("memory_prepared") is True
    and bool(object_value(runtime.get("memory")) or list_value(runtime.get("persisted_memory_events"))),
    detail="Generation/update summary memory must be prepared and persisted for future turns.",
    missing=missing_memory_fields(runtime),
  )
  add_check(
    checks,
    name="commit_after_validation",
    passed=completion_status.get("files_committed") is True
    and final_output.get("preview_status") == "ready"
    and int_value(final_output.get("file_count")) > 0,
    detail="Files must be committed only after validated staged preview is ready.",
    missing=missing_commit_fields(runtime),
  )

  if intent == "website_update":
    add_check(
      checks,
      name="update_preserves_context",
      passed=runtime.get("operation") == "update" and bool(list_value(final_output.get("changed_file_paths"))),
      detail="Update mode must report changed paths after merging generated changes with previous project files.",
      missing=[] if bool(list_value(final_output.get("changed_file_paths"))) else ["final_output.changed_file_paths"],
    )
