from __future__ import annotations

from pathlib import Path


_NAVIGATION_SCRIPT_PATH = Path(__file__).with_name("navigation_script.js")


def preview_navigation_guard_script(*, base_href: str, project_id: str = "", version_id: str = "") -> str:
  """Keep preview navigation under the version prefix and expose app routes to generated SPAs."""
  template = _NAVIGATION_SCRIPT_PATH.read_text(encoding="utf-8")
  return (
    template.replace("__BASE_HREF__", base_href)
    .replace("__PROJECT_ID__", project_id)
    .replace("__VERSION_ID__", version_id)
  )
