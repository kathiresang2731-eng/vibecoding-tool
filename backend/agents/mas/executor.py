from __future__ import annotations

import time
from typing import Any

from .contracts import AgentHandoff, AgentInput, AgentOutput, MASContractError, MAS_RUNTIME_NAME, MASRunState, utc_now_iso
from .graph import COMMIT_GATE_ACTIONS, agent_contract_for_action, ordered_runtime_agent_contracts


def ensure_mas_run(state: dict[str, Any]) -> dict[str, Any]:
  mas_run = state.get("mas_run")
  if isinstance(mas_run, dict):
    return mas_run

  mas = MASRunState(
    runtime=MAS_RUNTIME_NAME,
    project_id=str(state.get("project_id") or ""),
    prompt=str(state.get("prompt") or ""),
    routing_result=state.get("routing_result") if isinstance(state.get("routing_result"), dict) else {},
    contracts=ordered_runtime_agent_contracts(),
    guardrails={
      "commit_requires": list(COMMIT_GATE_ACTIONS),
      "backend_authority": [
        "path safety",
        "tool execution",
        "validation",
        "staged preview",
        "visual QA",
        "file commit",
        "memory persistence",
      ],
      "model_authority": ["routing", "analysis", "planning", "code proposal", "repair proposal"],
    },
  ).to_dict()
  state["mas_run"] = mas
  return mas


def assert_mas_action_allowed(state: dict[str, Any], action: str) -> None:
  if action != "WRITE_PROJECT_FILES":
    return

  validation_status = _object(state.get("validation_result")).get("status")
  preview_status = _object(_object(state.get("preview_result")).get("version")).get("status")
  visual_qa_status = _object(state.get("visual_qa_result")).get("status")
  missing: list[str] = []
  if validation_status != "valid":
    missing.append("VALIDATE_PROJECT_ARTIFACT")
  if preview_status != "ready":
    missing.append("BUILD_STAGED_PROJECT_PREVIEW")
  if visual_qa_status != "passed":
    missing.append("RUN_PREVIEW_VISUAL_QA")
  if missing:
    raise MASContractError(
      "MAS commit gate blocked WRITE_PROJECT_FILES because required gates are not satisfied: "
      + ", ".join(missing)
    )


def begin_mas_action(
  state: dict[str, Any],
  *,
  action: str,
  agent: str,
  decision: dict[str, Any],
) -> dict[str, Any]:
  mas_run = ensure_mas_run(state)
  contract = agent_contract_for_action(action, agent_name=agent)
  step_id = f"mas-step-{len(mas_run.get('steps') or []) + 1:03d}"
  agent_input = AgentInput(
    action=action,
    prompt=str(state.get("prompt") or ""),
    project_id=str(state.get("project_id") or ""),
    routing_intent=str(_object(state.get("routing_result")).get("intent") or ""),
    decision={
      "next_agent": decision.get("next_agent"),
      "next_action": decision.get("next_action"),
      "reason": decision.get("reason"),
      "audit_id": decision.get("audit_id"),
    },
    context_refs={
      "has_read_result": bool(state.get("read_result")),
      "has_memory_result": bool(state.get("memory_result")),
      "has_generated_website": bool(state.get("generated_website")),
      "repair_attempts": int(state.get("repair_attempts") or 0),
    },
  )
  started_at = utc_now_iso()
  active = {
    "step_id": step_id,
    "contract": contract.to_dict(),
    "input": agent_input.to_dict(),
    "started_at": started_at,
    "_started_monotonic": time.monotonic(),
  }
  state["_active_mas_action"] = active
  return active


def complete_mas_action(
  state: dict[str, Any],
  *,
  action: str,
  agent: str,
  before_step_count: int,
  before_tool_call_count: int,
) -> dict[str, Any]:
  active = _active_action_or_default(state, action=action, agent=agent)
  output = _agent_output_payload(state, before_step_count=before_step_count)
  tool_calls = _new_tool_calls(state, before_tool_call_count=before_tool_call_count)
  return _record_mas_step(
    state,
    action=action,
    agent=agent,
    active=active,
    output=output,
    tool_calls=tool_calls,
    status="completed",
  )


def fail_mas_action(
  state: dict[str, Any],
  *,
  action: str,
  agent: str,
  error: Exception,
  before_step_count: int,
  before_tool_call_count: int,
) -> dict[str, Any]:
  active = _active_action_or_default(state, action=action, agent=agent)
  tool_calls = _new_tool_calls(state, before_tool_call_count=before_tool_call_count)
  return _record_mas_step(
    state,
    action=action,
    agent=agent,
    active=active,
    output={"error": str(error)[:1200]},
    tool_calls=tool_calls,
    status="failed",
    error=str(error),
  )


def build_mas_runtime_summary(state: dict[str, Any]) -> dict[str, Any]:
  mas_run = ensure_mas_run(state)
  if state.get("completed"):
    mas_run["status"] = "completed"
  elif mas_run.get("status") not in {"failed", "cancelled"}:
    mas_run["status"] = "running"
  mas_run["completed_at"] = mas_run.get("completed_at") or (utc_now_iso() if state.get("completed") else "")
  mas_run["completion_gates"] = {
    "artifact_valid": _object(state.get("validation_result")).get("status") == "valid",
    "staged_preview_ready": _object(_object(state.get("preview_result")).get("version")).get("status") == "ready",
    "visual_qa_passed": _object(state.get("visual_qa_result")).get("status") == "passed",
    "files_committed": bool(state.get("committed")),
    "memory_persisted": bool(state.get("memory")),
  }
  mas_run["step_count"] = len(mas_run.get("steps") or [])
  mas_run["handoff_count"] = len(mas_run.get("handoffs") or [])
  return mas_run


def _record_mas_step(
  state: dict[str, Any],
  *,
  action: str,
  agent: str,
  active: dict[str, Any],
  output: dict[str, Any],
  tool_calls: list[dict[str, Any]],
  status: str,
  error: str = "",
) -> dict[str, Any]:
  mas_run = ensure_mas_run(state)
  completed_at = utc_now_iso()
  started_monotonic = active.get("_started_monotonic")
  duration_ms = round((time.monotonic() - float(started_monotonic)) * 1000) if isinstance(started_monotonic, (int, float)) else 0
  contract = _object(active.get("contract"))
  step = AgentOutput(
    step_id=str(active.get("step_id") or f"mas-step-{len(mas_run.get('steps') or []) + 1:03d}"),
    contract_id=str(contract.get("id") or ""),
    agent=agent,
    action=action,
    status=status,
    input=_object(active.get("input")),
    output=output,
    tool_calls=tool_calls,
    started_at=str(active.get("started_at") or completed_at),
    completed_at=completed_at,
    duration_ms=duration_ms,
    error=error[:1200] if error else "",
  ).to_dict()
  previous = (mas_run.get("steps") or [])[-1] if mas_run.get("steps") else None
  mas_run.setdefault("steps", []).append(step)
  if previous:
    handoff = AgentHandoff(
      handoff_id=f"mas-handoff-{len(mas_run.get('handoffs') or []) + 1:03d}",
      sequence=len(mas_run.get("handoffs") or []) + 1,
      from_agent=str(previous.get("agent") or "Source Agent"),
      to_agent=agent,
      from_action=str(previous.get("action") or "completed_agent_step"),
      to_action=action,
      status="completed" if status == "completed" else "failed",
      input=_object(step.get("input")),
      output=_object(previous.get("output")),
      requested_tool_calls=[call.get("name") for call in tool_calls if isinstance(call, dict) and call.get("name")],
      contract_id=str(contract.get("id") or ""),
    ).to_dict()
    mas_run.setdefault("handoffs", []).append(handoff)
  if status == "failed":
    mas_run["status"] = "failed"
    mas_run["completed_at"] = completed_at
  state.pop("_active_mas_action", None)
  return step


def _active_action_or_default(state: dict[str, Any], *, action: str, agent: str) -> dict[str, Any]:
  active = state.get("_active_mas_action")
  if isinstance(active, dict):
    return active
  return begin_mas_action(state, action=action, agent=agent, decision={"next_agent": agent, "next_action": action, "reason": "Recovered missing MAS action start."})


def _agent_output_payload(state: dict[str, Any], *, before_step_count: int) -> dict[str, Any]:
  new_steps = [
    step
    for step in list(state.get("agent_steps") or [])[before_step_count:]
    if isinstance(step, dict)
  ]
  if not new_steps:
    return {"status": "completed"}
  if len(new_steps) == 1:
    return _object(new_steps[0].get("output"))
  return {
    "status": "completed",
    "steps": [
      {
        "agent": step.get("agent"),
        "action": step.get("action"),
        "output": _object(step.get("output")),
      }
      for step in new_steps
    ],
  }


def _new_tool_calls(state: dict[str, Any], *, before_tool_call_count: int) -> list[dict[str, Any]]:
  return [
    _compact_tool_call(call)
    for call in list(state.get("tool_calls") or [])[before_tool_call_count:]
    if isinstance(call, dict)
  ]


def _compact_tool_call(call: dict[str, Any]) -> dict[str, Any]:
  return {
    "call_id": call.get("call_id"),
    "name": call.get("name"),
    "agent": call.get("agent"),
    "status": call.get("status"),
    "error": call.get("error"),
  }


def _object(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}
