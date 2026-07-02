from __future__ import annotations

from typing import Any

from ..a2a_communication import CANONICAL_HANDOFF_REQUIRED_FIELDS
from .values import int_value, list_value, object_value, text_value


def missing_gemini_native_provider_fields(tool_setup: dict[str, Any]) -> list[str]:
  missing: list[str] = []
  if tool_setup.get("provider") != "gemini-native-control-artifact":
    missing.append("gemini_tool_calling_setup.provider == gemini-native-control-artifact")
  if not text_value(tool_setup.get("control_provider")):
    missing.append("gemini_tool_calling_setup.control_provider")
  if not text_value(tool_setup.get("artifact_provider")):
    missing.append("gemini_tool_calling_setup.artifact_provider")
  return missing

def missing_conversation_provider_fields(tool_setup: dict[str, Any]) -> list[str]:
  missing: list[str] = []
  if tool_setup.get("provider") != "gemini-native-control-artifact":
    missing.append("gemini_tool_calling_setup.provider == gemini-native-control-artifact")
  if not text_value(tool_setup.get("control_provider")):
    missing.append("gemini_tool_calling_setup.control_provider")
  artifact_provider = text_value(tool_setup.get("artifact_provider"))
  if artifact_provider and artifact_provider != "not-used":
    missing.append("gemini_tool_calling_setup.artifact_provider == not-used")
  return missing

def missing_artifact_branch_fields(runtime: dict[str, Any], intent: str) -> list[str]:
  missing: list[str] = []
  expected_operation = "update" if intent == "website_update" else "generate"
  if runtime.get("tool_source_of_truth") is not True:
    missing.append("agentic_runtime.tool_source_of_truth")
  if runtime.get("branch") != intent:
    missing.append("agentic_runtime.branch")
  if runtime.get("operation") != expected_operation:
    missing.append("agentic_runtime.operation")
  return missing

def missing_preview_fields(runtime: dict[str, Any]) -> list[str]:
  completion_status = object_value(runtime.get("completion_status"))
  visual_qa = object_value(runtime.get("visual_qa"))
  missing: list[str] = []
  if completion_status.get("staged_preview_ready") is not True:
    missing.append("agentic_runtime.completion_status.staged_preview_ready")
  if completion_status.get("visual_qa_passed") is not True:
    missing.append("agentic_runtime.completion_status.visual_qa_passed")
  if visual_qa.get("status") != "passed":
    missing.append("agentic_runtime.visual_qa.status == passed")
  return missing

def missing_supervisor_fields(runtime: dict[str, Any]) -> list[str]:
  missing: list[str] = []
  if not list_value(runtime.get("supervisor_audit_trail")):
    missing.append("agentic_runtime.supervisor_audit_trail")
  if object_value(runtime.get("completion_proof")).get("satisfied") is not True:
    missing.append("agentic_runtime.completion_proof.satisfied")
  return missing

def missing_a2a_fields(a2a_runtime: dict[str, Any], handoffs: list[Any]) -> list[str]:
  messages = list_value(a2a_runtime.get("messages"))
  missing: list[str] = []
  if not messages:
    missing.append("agent_to_agent_communication.a2a_runtime.messages")
  if not handoffs:
    missing.append("agent_to_agent_communication.agentic_handoffs")
  candidates = [*messages, *handoffs]
  if not candidates:
    return missing
  for index, item in enumerate(candidates, start=1):
    if not isinstance(item, dict):
      missing.append(f"a2a_message[{index}]")
      continue
    for field in CANONICAL_HANDOFF_REQUIRED_FIELDS:
      if field not in item:
        missing.append(f"a2a_message[{index}].{field}")
    confidence = item.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
      missing.append(f"a2a_message[{index}].confidence")
  return missing

def missing_memory_fields(runtime: dict[str, Any]) -> list[str]:
  missing: list[str] = []
  if object_value(runtime.get("completion_status")).get("memory_prepared") is not True:
    missing.append("agentic_runtime.completion_status.memory_prepared")
  if not object_value(runtime.get("memory")) and not list_value(runtime.get("persisted_memory_events")):
    missing.append("agentic_runtime.memory")
  return missing

def missing_commit_fields(runtime: dict[str, Any]) -> list[str]:
  completion_status = object_value(runtime.get("completion_status"))
  final_output = object_value(runtime.get("final_output"))
  missing: list[str] = []
  if completion_status.get("files_committed") is not True:
    missing.append("agentic_runtime.completion_status.files_committed")
  if final_output.get("preview_status") != "ready":
    missing.append("agentic_runtime.final_output.preview_status == ready")
  if int_value(final_output.get("file_count")) <= 0:
    missing.append("agentic_runtime.final_output.file_count > 0")
  return missing

def missing_failure_detail_fields(payload: dict[str, Any]) -> list[str]:
  missing: list[str] = []
  if not text_value(object_value(payload.get("detail")).get("raw_error")):
    missing.append("detail.raw_error")
  if not text_value(object_value(payload.get("detail")).get("provider")) and not text_value(payload.get("category")):
    missing.append("detail.provider or category")
  return missing
