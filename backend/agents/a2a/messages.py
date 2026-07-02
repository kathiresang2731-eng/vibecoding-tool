from __future__ import annotations

from typing import Any

from .constants import A2A_PROTOCOL_VERSION, ACTION_CHANNELS
from .contracts import build_canonical_handoff_contract
from .utils import list_value, object_value, slug, text_value


def build_a2a_message(
  *,
  sequence: int,
  source: dict[str, Any],
  target: dict[str, Any],
  runtime: str,
  branch: str,
) -> dict[str, Any]:
  source_agent = text_value(source.get("agent"), "Source Agent")
  target_agent = text_value(target.get("agent"), "Target Agent")
  source_action = text_value(source.get("action"), "completed_agent_step")
  target_action = text_value(target.get("action"), "run_next_agent_step")
  channel = ACTION_CHANNELS.get(target_action, "planning")
  message_id = f"a2a-{sequence}-{slug(source_agent)}-to-{slug(target_agent)}"
  source_output = object_value(source.get("output"))
  target_input = object_value(target.get("input"))
  requested_tool_calls = list_value(target.get("tool_calls"))
  canonical_contract = build_canonical_handoff_contract(
    source_agent=source_agent,
    target_agent=target_agent,
    source_action=source_action,
    target_action=target_action,
    source_output=source_output,
    target_input=target_input,
    requested_tool_calls=requested_tool_calls,
  )
  return {
    "message_id": message_id,
    "correlation_id": f"{runtime}:{branch}",
    "protocol": A2A_PROTOCOL_VERSION,
    "sequence": sequence,
    "channel": channel,
    "type": "agent_handoff",
    "from_agent": source_agent,
    "to_agent": target_agent,
    "sender": canonical_contract["sender"],
    "receiver": canonical_contract["receiver"],
    "task": canonical_contract["task"],
    "input": canonical_contract["input"],
    "output": canonical_contract["output"],
    "confidence": canonical_contract["confidence"],
    "next_action": canonical_contract["next_action"],
    "intent": target_action,
    "status": "delivered",
    "requires_ack": True,
    "summary": f"{source_agent} completed {source_action} and handed off to {target_agent}.",
    "payload": {
      "completed_action": source_action,
      "next_action": target_action,
      "source_output": source_output,
      "target_input": target_input,
      "requested_tool_calls": requested_tool_calls,
      "handoff_contract": canonical_contract,
      "contract": {
        "input_schema": "json_object",
        "output_schema": "json_object",
        "private_reasoning_allowed": False,
      },
    },
  }


def build_a2a_message_from_handoff(
  *,
  sequence: int,
  handoff: dict[str, Any],
  runtime: str,
  branch: str,
) -> dict[str, Any]:
  source_agent = text_value(handoff.get("from_agent"), "Source Agent")
  target_agent = text_value(handoff.get("to_agent"), "Target Agent")
  source_action = text_value(handoff.get("from_action"), "completed_agent_step")
  target_action = text_value(handoff.get("to_action"), "run_next_agent_step")
  requested_tool_calls = list_value(handoff.get("requested_tool_calls"))
  source_output = object_value(handoff.get("output"))
  target_input = object_value(handoff.get("input"))
  channel = channel_for_action(target_action)
  message_id = f"a2a-{sequence}-{slug(source_agent)}-to-{slug(target_agent)}"
  canonical_contract = build_canonical_handoff_contract(
    source_agent=source_agent,
    target_agent=target_agent,
    source_action=source_action,
    target_action=target_action,
    source_output=source_output,
    target_input=target_input,
    requested_tool_calls=requested_tool_calls,
  )
  return {
    "message_id": message_id,
    "correlation_id": f"{runtime}:{branch}",
    "protocol": A2A_PROTOCOL_VERSION,
    "sequence": sequence,
    "channel": channel,
    "type": "agent_handoff",
    "from_agent": source_agent,
    "to_agent": target_agent,
    "sender": canonical_contract["sender"],
    "receiver": canonical_contract["receiver"],
    "task": canonical_contract["task"],
    "input": canonical_contract["input"],
    "output": canonical_contract["output"],
    "confidence": canonical_contract["confidence"],
    "next_action": canonical_contract["next_action"],
    "intent": target_action,
    "status": "delivered",
    "requires_ack": True,
    "summary": f"{source_agent} completed {source_action} and handed off to {target_agent}.",
    "payload": {
      "completed_action": source_action,
      "next_action": target_action,
      "source_output": source_output,
      "target_input": target_input,
      "requested_tool_calls": requested_tool_calls,
      "handoff_contract": canonical_contract,
      "contract": {
        "input_schema": "json_object",
        "output_schema": "json_object",
        "private_reasoning_allowed": False,
      },
      "source": text_value(handoff.get("source"), "real_mas_runtime"),
    },
  }


def channel_for_action(action: str) -> str:
  if action in ACTION_CHANNELS:
    return ACTION_CHANNELS[action]
  upper = action.upper()
  if upper in {"READ_PROJECT_FILES", "LOAD_PROJECT_MEMORY", "PERSIST_PROJECT_MEMORY"}:
    return "memory"
  if upper in {"RUN_UPDATE_ANALYST", "RUN_ERROR_HANDLING_AGENT", "RUN_PROMPT_ANALYST"}:
    return "analysis"
  if upper in {"RUN_PLANNER", "RUN_DYNAMIC_AGENT_PLANNER", "RUN_DYNAMIC_SPECIALISTS"}:
    return "planning"
  if upper in {"RUN_UX_REVIEW_AGENT"}:
    return "ux_review"
  if upper in {"RUN_ACCESSIBILITY_AGENT"}:
    return "accessibility"
  if upper in {"RUN_CODE_AGENT", "RUN_SCOPED_UPDATE_AGENT", "RUN_DYNAMIC_PATCH_INTEGRATOR", "WRITE_PROJECT_FILES"}:
    return "artifact"
  if upper in {"RUN_REPAIR_AGENT"}:
    return "repair"
  if upper in {"VALIDATE_PROJECT_ARTIFACT"}:
    return "validation"
  if upper in {"BUILD_STAGED_PROJECT_PREVIEW"}:
    return "preview"
  if upper in {"RUN_PREVIEW_VISUAL_QA"}:
    return "visual_qa"
  return "planning"


def build_acknowledgement(message: dict[str, Any]) -> dict[str, Any]:
  return {
    "ack_id": f"ack-{message['message_id']}",
    "message_id": message["message_id"],
    "from_agent": message["to_agent"],
    "to_agent": message["from_agent"],
    "status": "accepted",
    "sequence": message["sequence"],
    "acknowledged_next_action": message.get("next_action"),
  }
