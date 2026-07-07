# Requirement Confirmation

This package owns the approval step that pauses high-impact website generation
or update work until the user confirms a concrete execution brief.

- `prompts.py` builds model prompts and embeds JSON contracts.
- `service.py` calls the control model and logs confirmation decisions.
- `storage.py` persists and resolves pending confirmation briefs.
- `normalization.py` validates model output and deterministic fallbacks.
- `presentation.py` formats user-facing confirmation messages.
- `routing.py` maps confirmation state back into orchestration routing.
- `constants.py` and `values.py` hold shared primitives.

Import public helpers from `backend.agents.requirement_confirmation`.
