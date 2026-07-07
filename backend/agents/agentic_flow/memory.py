from __future__ import annotations

from typing import Any

from .values import list_value, text_value


def generation_memory_content(generated_website: dict[str, Any], files: list[Any]) -> str:
  title = text_value(generated_website.get("title"), "Untitled website")
  sections = list_value(generated_website.get("sections"))
  section_names = [
    text_value(section.get("name"), "")
    for section in sections
    if isinstance(section, dict) and text_value(section.get("name"), "")
  ]
  section_summary = ", ".join(section_names[:8]) or "no named sections"
  return f"Generated {title} with {len(files)} files. Sections: {section_summary}."
