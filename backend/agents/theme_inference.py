from __future__ import annotations

import re
from typing import Any


HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
THEME_COLOR_KEYS = ("primary", "secondary", "accent", "background", "text")


class ThemeContractError(ValueError):
  """Raised when a generated artifact is missing LLM/user-provided theme data."""


def infer_contextual_theme(*text_parts: Any, style_fallback: str = "") -> dict[str, Any]:
  """Extract an explicitly provided theme from context.

  This function intentionally does not generate, infer, rotate, or map colors.
  The backend is allowed to validate and preserve theme values, not design a
  static or fallback website theme. If required colors are missing, the caller
  must repair/retry through the LLM instead of silently inventing colors here.
  """
  context = _join_context(text_parts)
  colors = _extract_keyed_hex_colors(context)
  missing = [key for key in THEME_COLOR_KEYS if key not in colors]
  if missing:
    raise ThemeContractError(
      "Generated website theme is missing LLM/user-provided colors: "
      + ", ".join(missing)
      + ". Retry the model artifact with explicit theme.colors values."
    )
  return {
    "colors": {key: colors[key] for key in THEME_COLOR_KEYS},
    "style_direction": _style_direction_from_context(context, style_fallback),
  }


def merge_theme_with_context(theme: Any, *text_parts: Any, style_fallback: str = "") -> dict[str, Any]:
  """Preserve a complete LLM/user theme and reject backend fallback colors."""
  source_colors = theme.get("colors") if isinstance(theme, dict) and isinstance(theme.get("colors"), dict) else {}
  colors = {
    key: str(source_colors.get(key) or "").strip()
    for key in THEME_COLOR_KEYS
    if HEX_COLOR_RE.match(str(source_colors.get(key) or "").strip())
  }
  if len(colors) != len(THEME_COLOR_KEYS):
    context = _join_context([*text_parts, *(source_colors.values() if isinstance(source_colors, dict) else [])])
    context_colors = _extract_keyed_hex_colors(context)
    for key in THEME_COLOR_KEYS:
      if key not in colors and key in context_colors:
        colors[key] = context_colors[key]

  missing = [key for key in THEME_COLOR_KEYS if key not in colors]
  if missing:
    raise ThemeContractError(
      "Generated website theme must provide all colors from the LLM/user artifact; missing: "
      + ", ".join(missing)
      + ". Backend static or generated color fallback is disabled."
    )

  style_direction = ""
  if isinstance(theme, dict):
    style_direction = str(theme.get("style_direction") or "").strip()
  if not style_direction:
    style_direction = _style_direction_from_context(_join_context(text_parts), style_fallback)
  if not style_direction:
    raise ThemeContractError(
      "Generated website theme.style_direction is missing. Backend static theme fallback is disabled."
    )

  return {
    "colors": {key: colors[key] for key in THEME_COLOR_KEYS},
    "style_direction": style_direction,
  }


def _join_context(text_parts: list[Any] | tuple[Any, ...]) -> str:
  return " ".join(str(part or "") for part in text_parts).strip()


def _extract_keyed_hex_colors(text: str) -> dict[str, str]:
  colors: dict[str, str] = {}
  if not text:
    return colors
  for key in THEME_COLOR_KEYS:
    key_pattern = re.escape(key)
    before_hex = re.search(
      rf"\b{key_pattern}\b[^#]{{0,80}}(#[0-9a-fA-F]{{6}})\b",
      text,
      flags=re.IGNORECASE,
    )
    if before_hex:
      colors[key] = before_hex.group(1)
      continue
    after_hex = re.search(
      rf"(#[0-9a-fA-F]{{6}})\b[^A-Za-z0-9#]{{0,80}}\b{key_pattern}\b",
      text,
      flags=re.IGNORECASE,
    )
    if after_hex:
      colors[key] = after_hex.group(1)
  return colors


def _style_direction_from_context(context: str, fallback: str) -> str:
  if fallback:
    return fallback
  brief = " ".join((context or "").split())
  if not brief:
    return ""
  words = brief.split()
  snippet = " ".join(words[:18])
  suffix = "..." if len(words) > 18 else ""
  return f"LLM/user-provided theme direction: {snippet}{suffix}"
