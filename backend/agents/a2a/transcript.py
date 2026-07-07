from __future__ import annotations

from typing import Any

from .constants import A2A_CHANNEL_POLICY, A2A_PROTOCOL_VERSION, CANONICAL_HANDOFF_REQUIRED_FIELDS
from .errors import A2AProtocolError
from .messages import build_a2a_message, build_a2a_message_from_handoff, build_acknowledgement
from .utils import list_value, object_value, text_value
from .validation import validate_a2a_transcript


def build_a2a_communication(agentic_flow: dict[str, Any]) -> dict[str, Any]:
  steps = list_value(agentic_flow.get("steps"))
  mas_handoffs = list_value(object_value(agentic_flow.get("mas_runtime")).get("handoffs"))
  live_messages = list_value(agentic_flow.get("a2a_messages"))
  if not steps and not mas_handoffs and not live_messages:
    raise A2AProtocolError("A2A communication requires at least one agent step.")

  runtime_name = text_value(agentic_flow.get("runtime"), "unknown-runtime")
  branch = text_value(agentic_flow.get("branch"), "unknown")
  if live_messages:
    messages = live_messages
    acknowledgements = list_value(agentic_flow.get("a2a_acknowledgements")) or [
      build_acknowledgement(message) for message in live_messages
    ]
    projection_source = "live_a2a_bus"
    source_of_truth = True
  elif mas_handoffs:
    messages = [
      build_a2a_message_from_handoff(
        sequence=sequence,
        handoff=handoff,
        runtime=runtime_name,
        branch=branch,
      )
      for sequence, handoff in enumerate(mas_handoffs, start=1)
      if isinstance(handoff, dict)
    ]
    projection_source = "mas_runtime_handoffs"
    source_of_truth = True
    acknowledgements = [build_acknowledgement(message) for message in messages]
  else:
    messages = [
      build_a2a_message(
        sequence=sequence,
        source=source,
        target=target,
        runtime=runtime_name,
        branch=branch,
      )
      for sequence, (source, target) in enumerate(zip(steps, steps[1:]), start=1)
    ]
    acknowledgements = [build_acknowledgement(message) for message in messages]
    projection_source = "real_agent_runtime_steps"
    source_of_truth = False
  runtime = {
    "protocol": A2A_PROTOCOL_VERSION,
    "runtime": "worktual-python-a2a-communication",
    "status": "completed",
    "branch": branch,
    "source_of_truth": source_of_truth,
    "source_of_truth_runtime": runtime_name,
    "projection_source": projection_source,
    "channel_policy": A2A_CHANNEL_POLICY,
    "handoff_contract_fields": list(CANONICAL_HANDOFF_REQUIRED_FIELDS),
    "message_count": len(messages),
    "ack_count": len(acknowledgements),
    "messages": messages,
    "acknowledgements": acknowledgements,
  }
  runtime["validation"] = validate_a2a_transcript(runtime)
  return runtime
