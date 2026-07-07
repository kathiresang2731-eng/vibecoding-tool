from __future__ import annotations

import re

from .navigation import preview_navigation_guard_script
from .paths import preview_base_path


def rewrite_preview_html(html: str, *, project_id: str = "", version_id: str = "") -> str:
  updated = (
    html.replace('src="/assets/', 'src="./assets/')
    .replace("src='/assets/", "src='./assets/")
    .replace('href="/assets/', 'href="./assets/')
    .replace("href='/assets/", "href='./assets/")
  )
  if not project_id or not version_id:
    return updated

  base_href = preview_base_path(project_id, version_id)
  base_tag = f'<base href="{base_href}">'
  if re.search(r"<base\s", updated, flags=re.IGNORECASE):
    updated = re.sub(
      r"<base\s[^>]*>",
      base_tag,
      updated,
      count=1,
      flags=re.IGNORECASE,
    )
  elif re.search(r"<head[^>]*>", updated, flags=re.IGNORECASE):
    updated = re.sub(
      r"(<head[^>]*>)",
      rf"\1\n  {base_tag}",
      updated,
      count=1,
      flags=re.IGNORECASE,
    )
  else:
    updated = f"{base_tag}\n{updated}"

  guard = preview_navigation_guard_script(base_href=base_href, project_id=project_id, version_id=version_id)
  if "__WORKTUAL_PREVIEW_NAV_GUARD__" not in updated:
    script = f"<script>{guard}</script>"
    if re.search(r"</head>", updated, flags=re.IGNORECASE):
      updated = re.sub(r"</head>", f"  {script}\n</head>", updated, count=1, flags=re.IGNORECASE)
    else:
      updated = f"{script}\n{updated}"

  return updated

