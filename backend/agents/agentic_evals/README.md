# Agentic evaluation helpers

This package evaluates generation responses against the Worktual agentic runtime contract.

- `core.py` routes normalized responses to artifact or conversation evaluation branches.
- `artifact.py` checks artifact-runtime requirements: Gemini provider metadata, required tools, preview/visual QA, supervisor proof, A2A, memory, and commit readiness.
- `conversation.py` checks conversation-only turns that must avoid artifact generation.
- `failure.py` validates structured failure payloads.
- `scoring.py` owns check scoring and summaries.
- `missing.py` centralizes missing-field diagnostics.
- `a2a.py` validates canonical agent-to-agent handoff payloads.
- `runtime.py` extracts runtime tool names.
- `values.py` contains small coercion helpers for safe evaluation.
- `constants.py` contains accepted intents and required fields/tools.

Import `evaluate_agentic_response` and `evaluate_failure_payload` from `backend.agents.agentic_evals`; the package keeps that public path stable.
