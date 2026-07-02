from __future__ import annotations

from typing import Any


NO_SPECIFICATION_PHRASES = (
  "no specification",
  "no specifications",
  "no specific",
  "no details",
  "no information",
  "don't have any",
  "dont have any",
  "use default",
  "use defaults",
  "just generate",
  "start generation",
)


# Keyword hints are optional metadata for the LLM domain-research step.
# No preset layouts or domain-specific generation blueprints are stored here.
DOMAIN_CATEGORY_HINTS: dict[str, dict[str, Any]] = {}

# Backward-compatible alias for existing imports.
DOMAIN_PROFILES = DOMAIN_CATEGORY_HINTS
