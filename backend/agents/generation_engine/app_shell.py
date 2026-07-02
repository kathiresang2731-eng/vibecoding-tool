from __future__ import annotations

import re
from typing import Any

try:
  from ..streaming.syntax_guard import syntax_issues_for_content
  from ..streaming.task_planner import _component_name_from_path, _relative_import_from_app
except ImportError:
  from backend.agents.streaming.syntax_guard import syntax_issues_for_content
  from backend.agents.streaming.task_planner import _component_name_from_path, _relative_import_from_app


def _route_path_for_page(path: str) -> str:
  base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
  if base.lower() == "home":
    return "/"
  slug = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", base).lower().replace("_", "-")
  return f"/{slug}"


def _valid_page_paths(page_paths: list[str], files_map: dict[str, str]) -> list[str]:
  valid: list[str] = []
  for path in sorted(page_paths):
    content = str(files_map.get(path) or "")
    if len(content.strip()) < 40:
      continue
    if syntax_issues_for_content(path, content):
      continue
    valid.append(path)
  return valid


def synthesize_greenfield_app_shell(
  page_paths: list[str],
  files_map: dict[str, str],
) -> str:
  valid_pages = _valid_page_paths(page_paths, files_map)
  if not valid_pages:
    valid_pages = ["src/pages/Home.jsx"]

  has_layout = bool(str(files_map.get("src/components/Layout.jsx") or "").strip())
  lines = [
    'import React from "react";',
    'import { HashRouter, Navigate, Route, Routes } from "react-router-dom";',
  ]
  if has_layout:
    lines.append('import Layout from "./components/Layout.jsx";')
  for path in valid_pages:
    name = _component_name_from_path(path)
    lines.append(f'import {name} from "{_relative_import_from_app(path)}";')

  lines.extend(["", "export default function App() {", "  return (", "    <HashRouter>"])
  if has_layout:
    lines.append("      <Layout>")
    lines.append("        <Routes>")
  else:
    lines.append("      <Routes>")

  indent = "          " if has_layout else "        "
  default_route = _route_path_for_page(valid_pages[0])
  if default_route != "/":
    lines.append(f'{indent}<Route path="/" element={{<Navigate to="{default_route}" replace />}} />')

  for path in valid_pages:
    name = _component_name_from_path(path)
    route_path = _route_path_for_page(path)
    lines.append(f'{indent}<Route path="{route_path}" element={{<{name} />}} />')

  if has_layout:
    lines.extend(["        </Routes>", "      </Layout>", "    </HashRouter>", "  );", "}", ""])
  else:
    lines.extend(["      </Routes>", "    </HashRouter>", "  );", "}", ""])
  return "\n".join(lines)


def app_shell_needs_repair(app_content: str, page_paths: list[str]) -> bool:
  content = str(app_content or "")
  if not content.strip():
    return True
  if syntax_issues_for_content("src/App.jsx", content):
    return True
  if "<Route" not in content:
    return True
  if re.search(r"element=\{<[^/>]{1,40}$", content, flags=re.MULTILINE):
    return True
  for path in page_paths:
    name = _component_name_from_path(path)
    if name not in content:
      return True
  return False


def apply_deterministic_app_shell(
  files_map: dict[str, str],
  *,
  work_plan: dict[str, Any] | None = None,
  force: bool = False,
) -> tuple[dict[str, str], bool]:
  page_paths = sorted(
    path
    for path in files_map
    if path.startswith("src/pages/") and path.endswith((".jsx", ".tsx"))
  )
  valid_pages = _valid_page_paths(page_paths, files_map)
  if work_plan and not valid_pages:
    planned_pages = [
      str(path)
      for task in (work_plan.get("tasks") or [])
      if isinstance(task, dict) and str(task.get("kind") or "").startswith("greenfield_page")
      for path in (task.get("paths") or [])
    ]
    valid_pages = _valid_page_paths(planned_pages, files_map)

  current_app = str(files_map.get("src/App.jsx") or "")
  if (
    not force
    and valid_pages
    and not app_shell_needs_repair(current_app, valid_pages)
    and not syntax_issues_for_content("src/App.jsx", current_app)
    and all(_component_name_from_path(path) in current_app for path in valid_pages)
  ):
    return files_map, False

  synthesized = synthesize_greenfield_app_shell(valid_pages or page_paths, files_map)
  if synthesized == current_app:
    return files_map, False
  updated = dict(files_map)
  updated["src/App.jsx"] = synthesized
  return updated, True
