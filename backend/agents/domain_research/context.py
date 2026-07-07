from __future__ import annotations

from typing import Any

from .inference import infer_domain_key
from .profiles import DOMAIN_CATEGORY_HINTS
from .values import text_values_from_mapping


def build_domain_research_context(
  prompt: str,
  *,
  memories: list[dict[str, Any]] | None = None,
  brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
  combined_text = combined_research_text(prompt, memories=memories, brief=brief)
  domain_key = infer_domain_key(combined_text)
  if not domain_key:
    return {
      "status": "hint",
      "source": "deterministic_domain_research",
      "domain": "generic",
      "display_name": "Website",
      "confidence": "low",
      "reason": "No category keywords were found. The LLM should infer layout, sections, and content from the user prompt.",
      "web_search_query": "",
      "assumptions": ["Do not use a fixed template; plan layout and content from the user's request."],
    }

  hint = DOMAIN_CATEGORY_HINTS[domain_key]
  display_name = str(hint["display_name"])
  return {
    "status": "hint",
    "source": "deterministic_domain_research",
    "domain": domain_key,
    "display_name": display_name,
    "confidence": "medium",
    "reason": (
      f"Detected {display_name} category keywords. "
      "The LLM should decide layout, sections, styling, and content — not a static template."
    ),
    "web_search_query": f"{display_name} website UX and content patterns",
    "assumptions": [
      f"Category hint: {display_name.lower()}.",
      "Plan pages, components, and copy from the user prompt and optional web search — not preset sections.",
    ],
  }


def combined_research_text(
  prompt: str,
  *,
  memories: list[dict[str, Any]] | None,
  brief: dict[str, Any] | None,
) -> str:
  parts = [prompt]
  if isinstance(brief, dict):
    for key in ("business_type", "audience", "goal", "style", "required_sections"):
      value = brief.get(key)
      if isinstance(value, list):
        parts.extend(str(item) for item in value)
      elif value is not None:
        parts.append(str(value))
  for memory in memories or []:
    if not isinstance(memory, dict):
      continue
    for key in ("content", "kind", "key"):
      value = memory.get(key)
      if isinstance(value, str):
        parts.append(value)
    metadata = memory.get("metadata_json") or memory.get("metadata")
    parts.extend(text_values_from_mapping(metadata))
  return "\n".join(parts).lower()
