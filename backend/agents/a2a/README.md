# Agent-to-agent communication modules

This package owns the A2A transcript projection for the website-builder agent runtime.

- `constants.py` defines protocol version, channel policy, action-to-channel routing, and canonical handoff fields.
- `contracts.py` builds the canonical handoff contract and confidence score.
- `messages.py` creates handoff messages and acknowledgements.
- `transcript.py` assembles the full A2A runtime transcript from agentic flow steps.
- `validation.py` validates transcript shape, sequencing, channels, acknowledgements, and canonical fields.
- `summary.py` returns the compact public runtime summary.
- `errors.py` and `utils.py` contain shared support code.

`backend/agents/a2a_communication.py` remains the compatibility facade for existing imports.
