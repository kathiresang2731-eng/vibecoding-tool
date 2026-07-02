from __future__ import annotations

from backend.agents.requirement_confirmation.normalization import (
  deterministic_confirmation_decision,
  looks_like_confirmation_reply,
)


def test_confirm_phrase_is_detected_without_model() -> None:
  decision = deterministic_confirmation_decision("Confirm and proceed with this execution brief.")
  assert decision is not None
  assert decision["decision"] == "confirm"
  assert looks_like_confirmation_reply("Confirm and proceed with this execution brief.")


def test_cancel_phrase_is_detected_without_model() -> None:
  decision = deterministic_confirmation_decision("Cancel the pending execution brief.")
  assert decision is not None
  assert decision["decision"] == "cancel"
