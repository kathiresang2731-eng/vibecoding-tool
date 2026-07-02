from __future__ import annotations

from typing import Any

from .utils import text_value

def build_memory_summary(
  *,
  prompt: str,
  intent: str,
  generated_website: dict[str, Any],
  file_count: int,
  response_message: str,
) -> str:
  if intent != "website_generation":
    return f"Prompt: {prompt}\nUser message was routed as {intent}. Assistant response: {response_message}"
  title = text_value(generated_website.get("title"), "Untitled website")
  sections = generated_website.get("sections") if isinstance(generated_website, dict) else []
  section_names = [
    text_value(section.get("name"), "")
    for section in sections
    if isinstance(section, dict) and text_value(section.get("name"), "")
  ]
  section_text = ", ".join(section_names[:8]) or "no named sections"
  return f"Prompt: {prompt}\nGenerated: {title}\nFiles: {file_count}\nSections: {section_text}"
