from __future__ import annotations

from typing import Any

try:
  from ...audit_logging import log_query_event
except ImportError:
  from audit_logging import log_query_event

from ..agentic_flow import agent_step
from .values import object_value


def initial_runtime_state(*, project_id: str, prompt: str, routing_result: dict[str, Any]) -> dict[str, Any]:
  operation = runtime_operation_from_routing(routing_result)
  requirement = build_conversation_requirement(prompt=prompt, routing_result=routing_result, operation=operation)
  return {
    "project_id": project_id,
    "prompt": prompt,
    "operation": operation,
    "messages": [],
    "routing_result": routing_result,
    "conversation_requirement": requirement,
    "update_analysis": None,
    "update_code_search_matches": [],
    "scoped_update": None,
    "scoped_update_task_results": [],
    "brief": None,
    "plan": None,
    "dynamic_workflow_plan": None,
    "dynamic_specialist_results": None,
    "dynamic_specialists_completed": False,
    "dynamic_agents_promoted": False,
    "dynamic_agent_registry": None,
    "dynamic_agent_executions": [],
    "candidate_changes": [],
    "candidate_change_summary": {"accepted_count": 0, "rejected_count": 0, "accepted": [], "rejected": []},
    "dynamic_patch_integrated": False,
    "dynamic_agent_lifecycle_decisions": [],
    "dynamic_agent_failure_recorded": False,
    "files": [],
    "changed_file_paths": [],
    "validation": None,
    "preview": None,
    "preview_result": None,
    "visual_qa_result": None,
    "automated_test_scope": None,
    "read_result": None,
    "memory_result": None,
    "artifact_response": None,
    "generated_website": None,
    "candidate_files": [],
    "code_diff_summary": {},
    "_last_code_diff_signature": "",
    "validation_result": None,
    "write_result": None,
    "ux_review": None,
    "accessibility_review": None,
    "tool_calls": [],
    "agent_steps": [],
    "supervisor_decisions": [],
    "supervisor_audit_trail": [],
    "supervisor_policy_fallbacks": [],
    "supervisor_completion_rejections": [],
    "action_history": [],
    "repair_errors": [],
    "repair_attempts": 0,
    "repair_failure_signatures": {},
    "repair_attempted_signatures": {},
    "latest_repair_failure_signature": "",
    "latest_repair_failure_source": "",
    "persisted_memory_events": [],
    "artifact_fallback": None,
    "deterministic_repair_events": [],
    "local_sync": None,
    "memory": None,
    "loaded_memory": [],
    "files_materialized": False,
    "materialized_file_paths": [],
    "materialized_file_signatures": {},
    "committed": False,
    "completed": False,
  }


def build_conversation_requirement(
  *,
  prompt: str,
  routing_result: dict[str, Any],
  operation: str,
) -> dict[str, Any]:
  intent = str(object_value(routing_result).get("intent") or ("website_update" if operation == "update" else "website_generation"))
  lowered = prompt.lower()
  validation_requirements = ["preserve_unmentioned_files", "validate_project_artifact"]
  if operation == "update":
    validation_requirements.extend(["minimal_patch", "staged_preview_before_commit"])
  if any(term in lowered for term in ("layout", "align", "overlap", "mobile", "responsive", "ui", "button", "card")):
    validation_requirements.append("visual_layout_qa")
  return {
    "schema": "worktual.conversation-requirement.v1",
    "original_user_message": prompt,
    "normalized_intent": intent,
    "requested_change": summarize_requested_change(prompt),
    "explicit_constraints": infer_explicit_constraints(prompt),
    "selected_files": [],
    "rejected_files": [],
    "risk_level": infer_requirement_risk(prompt=prompt, operation=operation),
    "validation_requirements": validation_requirements,
    "route_reason": str(object_value(routing_result).get("reason") or object_value(routing_result).get("routing_reason") or ""),
  }


def summarize_requested_change(prompt: str) -> str:
  text = " ".join(str(prompt or "").strip().split())
  return text[:500]


def infer_explicit_constraints(prompt: str) -> list[str]:
  lowered = str(prompt or "").lower()
  constraints: list[str] = []
  if any(term in lowered for term in ("don't delete", "do not delete", "without deleting", "preserve", "keep existing")):
    constraints.append("preserve_existing_files")
  if any(term in lowered for term in ("small change", "minor", "only", "just", "minimal")):
    constraints.append("minimal_change")
  if any(term in lowered for term in ("local folder", "uploaded folder", "existing code", "generated code")):
    constraints.append("respect_existing_project_context")
  if any(term in lowered for term in ("memory", "remember", "conversation", "previous")):
    constraints.append("use_conversation_memory")
  return constraints


def infer_requirement_risk(*, prompt: str, operation: str) -> str:
  lowered = str(prompt or "").lower()
  if any(term in lowered for term in ("delete", "remove files", "full rewrite", "regenerate", "auth", "payment", "secret", ".env")):
    return "high"
  if operation == "update" or any(term in lowered for term in ("fix", "bug", "error", "update", "change")):
    return "medium"
  return "low"


def refresh_conversation_requirement(
  state: dict[str, Any],
  *,
  update_analysis: dict[str, Any] | None = None,
  selected_files: list[str] | None = None,
  rejected_files: list[str] | None = None,
) -> dict[str, Any]:
  requirement = object_value(state.get("conversation_requirement"))
  if not requirement:
    requirement = build_conversation_requirement(
      prompt=str(state.get("prompt") or ""),
      routing_result=object_value(state.get("routing_result")),
      operation=str(state.get("operation") or "generate"),
    )
  if update_analysis:
    requirement["requested_change"] = str(update_analysis.get("summary") or requirement.get("requested_change") or "")[:500]
    requirement["selected_files"] = selected_files or [
      str(path)
      for path in (update_analysis.get("candidate_files") or [])
      if str(path).strip()
    ]
    requirement["rejected_files"] = rejected_files or []
    requirement["risk_level"] = "high" if update_analysis.get("update_mode") == "full_regeneration" else requirement.get("risk_level", "medium")
    requirement["route_reason"] = str(update_analysis.get("reason") or requirement.get("route_reason") or "")[:600]
    requirement["update_mode"] = str(update_analysis.get("update_mode") or "")
    requirement["execution_strategy"] = str(update_analysis.get("execution_strategy") or "")
    requirement["request_kind"] = str(update_analysis.get("request_kind") or "")
  state["conversation_requirement"] = requirement
  return requirement


def runtime_operation_from_routing(routing_result: dict[str, Any]) -> str:
  return "update" if object_value(routing_result).get("intent") == "website_update" else "generate"


def record_agent_message(
  state: dict[str, Any],
  *,
  from_agent: str,
  to_agent: str,
  content: str,
  action: str,
) -> None:
  state["messages"].append(
    {
      "from_agent": from_agent,
      "to_agent": to_agent,
      "content": content,
      "action": action,
    }
  )


def append_step(
  state: dict[str, Any],
  agent: str,
  action: str,
  input_payload: dict[str, Any],
  output_payload: dict[str, Any],
  *,
  tool_calls: list[str] | None = None,
) -> None:
  step = agent_step(
    index=len(state["agent_steps"]) + 1,
    agent=agent,
    action=action,
    input_payload=input_payload,
    output_payload=output_payload,
    tool_calls=tool_calls,
  )
  state["agent_steps"].append(step)
  log_query_event("runtime.step", payload=step)
