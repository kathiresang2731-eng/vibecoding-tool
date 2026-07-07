from __future__ import annotations

from typing import Any

from .constants import A2A_CHANNEL_POLICY, A2A_PROTOCOL_VERSION, CANONICAL_HANDOFF_REQUIRED_FIELDS
from .errors import A2AProtocolError
from .utils import list_value


def validate_a2a_transcript(transcript: dict[str, Any]) -> dict[str, Any]:
  messages = list_value(transcript.get("messages"))
  acknowledgements = list_value(transcript.get("acknowledgements"))
  if transcript.get("protocol") != A2A_PROTOCOL_VERSION:
    raise A2AProtocolError("A2A transcript has an unsupported protocol version.")
  if len(messages) != len(acknowledgements):
    raise A2AProtocolError("A2A transcript must have one acknowledgement for each message.")

  expected_sequence = 1
  ack_by_message_id = {
    ack.get("message_id"): ack
    for ack in acknowledgements
    if isinstance(ack, dict) and isinstance(ack.get("message_id"), str)
  }
  for message in messages:
    if not isinstance(message, dict):
      raise A2AProtocolError("A2A message must be an object.")
    if message.get("protocol") != A2A_PROTOCOL_VERSION:
      raise A2AProtocolError("A2A message has an unsupported protocol version.")
    if message.get("sequence") != expected_sequence:
      raise A2AProtocolError("A2A message sequence is not contiguous.")
    if message.get("channel") not in A2A_CHANNEL_POLICY:
      raise A2AProtocolError("A2A message uses an unknown channel.")
    if not message.get("from_agent") or not message.get("to_agent"):
      raise A2AProtocolError("A2A message requires source and target agents.")
    for field in CANONICAL_HANDOFF_REQUIRED_FIELDS:
      if field not in message:
        raise A2AProtocolError(f"A2A message missing canonical handoff field: {field}")
    confidence = message.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
      raise A2AProtocolError("A2A message confidence must be a number between 0 and 1.")
    if not message.get("requires_ack"):
      raise A2AProtocolError("A2A message must require acknowledgement.")

    ack = ack_by_message_id.get(message.get("message_id"))
    if not ack or ack.get("status") != "accepted":
      raise A2AProtocolError("A2A message acknowledgement is missing or not accepted.")
    if ack.get("from_agent") != message.get("to_agent") or ack.get("to_agent") != message.get("from_agent"):
      raise A2AProtocolError("A2A acknowledgement agents do not match the message.")
    expected_sequence += 1

  return {
    "status": "valid",
    "checked_messages": len(messages),
    "checked_acknowledgements": len(acknowledgements),
  }
