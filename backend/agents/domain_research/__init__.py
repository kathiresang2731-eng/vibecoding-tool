from __future__ import annotations

from .context import build_domain_research_context, combined_research_text
from .enrichment import enrich_brief_with_domain_research
from .inference import infer_domain_key, is_generic_sections, is_generic_value, no_specification_prompt, normalized_string_list
from .profiles import DOMAIN_CATEGORY_HINTS, DOMAIN_PROFILES, NO_SPECIFICATION_PHRASES


__all__ = [
  "NO_SPECIFICATION_PHRASES",
  "DOMAIN_CATEGORY_HINTS",
  "DOMAIN_PROFILES",
  "build_domain_research_context",
  "enrich_brief_with_domain_research",
  "combined_research_text",
  "infer_domain_key",
  "no_specification_prompt",
  "is_generic_value",
  "normalized_string_list",
  "is_generic_sections",
]
