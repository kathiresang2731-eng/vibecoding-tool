# Legacy LLM Import Path

The executable AI system now lives in `backend/agents/`.

This directory is intentionally only a compatibility namespace so existing
imports such as `backend.llm.providers` continue to work. New backend code
should import from `backend.agents`.

