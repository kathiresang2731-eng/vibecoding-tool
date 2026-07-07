from __future__ import annotations

from typing import Any

from .inference import is_generic_sections, is_generic_value, no_specification_prompt, normalized_string_list


def enrich_brief_with_domain_research(prompt: str, brief: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
  enriched = dict(brief)
  enriched["domain_research"] = research

  if research.get("status") != "applied":
    if research.get("domain") not in {"", "generic"} and is_generic_value(enriched.get("business_type"), {"website", "site", ""}):
      enriched["business_type"] = f"{research.get('display_name', 'Website')} Website"
    return enriched

  if is_generic_value(enriched.get("business_type"), {"website", "site", ""}) or no_specification_prompt(prompt):
    enriched["business_type"] = f"{research.get('display_name', 'Website')} Website"
  if is_generic_value(enriched.get("audience"), {"target users from the prompt", "visitors", ""}) or no_specification_prompt(prompt):
    if research.get("audience"):
      enriched["audience"] = str(research["audience"])
  if is_generic_value(enriched.get("goal"), {prompt.strip().lower(), ""}) or no_specification_prompt(prompt):
    if research.get("goal"):
      enriched["goal"] = str(research["goal"])
  if is_generic_value(enriched.get("style"), {"modern, responsive, navy/teal worktual-aligned ui", "modern, responsive, black/purple worktual-aligned ui", ""}) or no_specification_prompt(prompt):
    if research.get("style"):
      enriched["style"] = str(research["style"])

  current_sections = normalized_string_list(enriched.get("required_sections"))
  llm_sections = normalized_string_list(research.get("required_sections"))
  if llm_sections and (is_generic_sections(current_sections) or no_specification_prompt(prompt)):
    enriched["required_sections"] = llm_sections
  elif llm_sections:
    merged = current_sections[:]
    for section in llm_sections:
      if section not in merged:
        merged.append(section)
    enriched["required_sections"] = merged[:10]

  return enriched
