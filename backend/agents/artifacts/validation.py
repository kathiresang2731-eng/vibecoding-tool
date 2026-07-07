from __future__ import annotations

from typing import Any

from .constants import HEX_COLOR_RE, REQUIRED_APP_ENTRY
from .errors import ArtifactValidationError
from .fields import optional_text, required_text
from .paths import normalize_artifact_path
from .react import normalize_generated_file_code


def validate_project_artifact(generated_website: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(generated_website, dict):
    raise ArtifactValidationError("Generated website artifact must be an object.")

  title = required_text(generated_website, "title")
  headline = required_text(generated_website, "headline")
  subheadline = required_text(generated_website, "subheadline")
  primary_cta = required_text(generated_website, "primary_cta")
  secondary_cta = required_text(generated_website, "secondary_cta")
  preview_html = optional_text(generated_website.get("preview_html"))
  theme = validate_theme(generated_website.get("theme"))
  sections = validate_sections(generated_website.get("sections"))
  files = validate_files(generated_website.get("files"))
  design_tokens = optional_object(generated_website.get("design_tokens"))
  component_manifest = optional_object_list(generated_website.get("component_manifest"))
  seo = optional_object(generated_website.get("seo"))
  compliance = optional_object(generated_website.get("compliance"))

  return {
    "title": title,
    "headline": headline,
    "subheadline": subheadline,
    "primary_cta": primary_cta,
    "secondary_cta": secondary_cta,
    "preview_html": preview_html,
    "theme": theme,
    "design_tokens": design_tokens,
    "component_manifest": component_manifest,
    "seo": seo,
    "compliance": compliance,
    "sections": sections,
    "files": files,
  }


def optional_object(value: Any) -> dict[str, Any]:
  return value if isinstance(value, dict) else {}


def optional_object_list(value: Any) -> list[dict[str, Any]]:
  if not isinstance(value, list):
    return []
  return [item for item in value if isinstance(item, dict)]


def validate_theme(theme: Any) -> dict[str, Any]:
  if not isinstance(theme, dict):
    raise ArtifactValidationError("Generated website theme must be an object.")
  colors = theme.get("colors")
  if not isinstance(colors, dict):
    raise ArtifactValidationError("Generated website theme.colors must be an object.")

  normalized_colors = {}
  for key in ("primary", "secondary", "accent", "background", "text"):
    value = required_text(colors, key)
    if not HEX_COLOR_RE.match(value):
      raise ArtifactValidationError(f"Theme color must be a six-digit hex value: {key}")
    normalized_colors[key] = value

  return {
    "colors": normalized_colors,
    "style_direction": optional_text(theme.get("style_direction")) or "LLM/user provided theme",
  }


def validate_sections(sections: Any) -> list[dict[str, Any]]:
  if not isinstance(sections, list) or not sections:
    raise ArtifactValidationError("Generated website must include at least one section.")

  normalized = []
  for index, section in enumerate(sections, start=1):
    if not isinstance(section, dict):
      raise ArtifactValidationError(f"Section {index} must be an object.")
    items = section.get("items")
    if items is None:
      items = []
    if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
      raise ArtifactValidationError(f"Section {index}.items must be a list of non-empty strings.")
    normalized.append(
      {
        "name": required_text(section, "name"),
        "purpose": required_text(section, "purpose"),
        "content": required_text(section, "content"),
        "items": [item.strip() for item in items],
      }
    )
  return normalized


def validate_files(files: Any) -> list[dict[str, Any]]:
  if not isinstance(files, list) or not files:
    raise ArtifactValidationError("Generated website must include at least one file.")

  normalized = []
  seen_paths: set[str] = set()
  for index, file_item in enumerate(files, start=1):
    if not isinstance(file_item, dict):
      raise ArtifactValidationError(f"File {index} must be an object.")
    path = normalize_artifact_path(required_text(file_item, "path"))
    if path in seen_paths:
      raise ArtifactValidationError(f"Duplicate generated file path: {path}")
    seen_paths.add(path)
    code = normalize_generated_file_code(path, required_text(file_item, "code"))
    normalized.append(
      {
        "path": path,
        "purpose": optional_text(file_item.get("purpose")) or "Generated project file.",
        "code": code,
      }
    )

  if requires_frontend_entry(seen_paths) and REQUIRED_APP_ENTRY not in seen_paths:
    raise ArtifactValidationError(f"Generated website must include {REQUIRED_APP_ENTRY}.")

  return normalized


def requires_frontend_entry(paths: set[str]) -> bool:
  if REQUIRED_APP_ENTRY in paths:
    return True
  frontend_markers = {
    "src/main.jsx",
    "src/main.tsx",
    "src/index.css",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cjs",
    "vite.config.ts",
  }
  if paths & frontend_markers:
    return True
  frontend_source_extensions = (".jsx", ".tsx")
  return any(
    path.startswith(("src/components/", "src/pages/", "src/theme/", "src/seo/"))
    or (path.startswith("src/") and path.endswith(frontend_source_extensions))
    for path in paths
  )
