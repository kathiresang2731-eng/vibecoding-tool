from __future__ import annotations

import re
from typing import Any

try:
  from ..streaming.syntax_guard import syntax_issues_for_content
  from ..streaming.task_planner import (
    GREENFIELD_SCAFFOLD_PATHS,
    is_rich_greenfield_website_request,
    plan_greenfield_parallel_tasks,
  )
except ImportError:
  try:
    from backend.agents.streaming.syntax_guard import syntax_issues_for_content
    from backend.agents.streaming.task_planner import (
      GREENFIELD_SCAFFOLD_PATHS,
      is_rich_greenfield_website_request,
      plan_greenfield_parallel_tasks,
    )
  except ImportError:
    from agents.streaming.syntax_guard import syntax_issues_for_content
    from agents.streaming.task_planner import (
      GREENFIELD_SCAFFOLD_PATHS,
      is_rich_greenfield_website_request,
      plan_greenfield_parallel_tasks,
    )


def _files_map(project_files: list[dict[str, Any]]) -> dict[str, str]:
  return {
    str(item.get("path") or ""): str(item.get("content") or "")
    for item in project_files
    if isinstance(item, dict) and item.get("path")
  }


def _page_paths(files_map: dict[str, str]) -> list[str]:
  return sorted(path for path in files_map if path.startswith("src/pages/") and path.endswith((".jsx", ".tsx")))


def _app_has_routes(app_content: str) -> bool:
  lowered = app_content.lower()
  return "route" in lowered and ("<routes" in lowered or "createroute" in lowered or "route " in lowered)


def _planned_paths_missing(prompt: str, files_map: dict[str, str]) -> list[str]:
  plan = plan_greenfield_parallel_tasks(prompt)
  missing: list[str] = []
  for task in plan.get("tasks") or []:
    if not isinstance(task, dict):
      continue
    if str(task.get("kind") or "") == "greenfield_app_shell":
      continue
    for path in task.get("paths") or []:
      clean = str(path or "").strip()
      if not clean or clean in GREENFIELD_SCAFFOLD_PATHS:
        continue
      if clean not in files_map or len(str(files_map.get(clean) or "").strip()) < 40:
        missing.append(clean)
  return list(dict.fromkeys(missing))


def validate_generation_deliverable(
  *,
  prompt: str,
  project_files: list[dict[str, Any]],
  work_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
  files_map = _files_map(project_files)
  page_paths = _page_paths(files_map)
  rich = is_rich_greenfield_website_request(prompt)
  app_content = str(files_map.get("src/App.jsx") or "")
  only_scaffold = all(
    path in GREENFIELD_SCAFFOLD_PATHS or path == "package-lock.json"
    for path in files_map
    if not path.startswith(".")
  ) and len(page_paths) == 0

  issues: list[str] = []
  if rich and len(page_paths) < 2:
    issues.append("rich_greenfield_needs_multiple_pages")
  if only_scaffold:
    issues.append("scaffold_only_no_pages")
  if page_paths and app_content and not _app_has_routes(app_content):
    issues.append("app_missing_routes")

  missing_paths = _planned_paths_missing(prompt, files_map)
  if missing_paths:
    issues.append("planned_paths_missing")

  syntax_errors: list[str] = []
  for path in [*page_paths, "src/App.jsx"]:
    if path in files_map:
      syntax_errors.extend(syntax_issues_for_content(path, str(files_map.get(path) or "")))
  if syntax_errors:
    issues.append("syntax_errors")

  complete = not issues
  return {
    "complete": complete,
    "issues": issues,
    "page_count": len(page_paths),
    "page_paths": page_paths,
    "missing_paths": missing_paths,
    "syntax_errors": syntax_errors[:12],
    "rich_greenfield": rich,
    "can_resume": bool(missing_paths) or bool(syntax_errors) or (rich and len(page_paths) < 2),
    "work_plan": work_plan or plan_greenfield_parallel_tasks(prompt),
  }


def build_generation_resume_prompt(prompt: str, validation: dict[str, Any]) -> str:
  missing = list(validation.get("missing_paths") or [])
  issues = list(validation.get("issues") or [])
  lines = [
    str(prompt or "").strip(),
    "",
    "## Generation continuation required",
    "The first pass did not produce a complete application. Continue building — do not stop at scaffold/config files.",
  ]
  if missing:
    lines.append("Create or complete these files next:")
    lines.extend(f"- {path}" for path in missing[:20])
  if "app_missing_routes" in issues:
    lines.append("- Wire all generated pages in src/App.jsx with react-router-dom routes.")
  if "syntax_errors" in issues:
    lines.append("- Fix syntax errors in generated JSX before finishing (complete all Route elements and exports).")
    for err in list(validation.get("syntax_errors") or [])[:6]:
      lines.append(f"  - {err}")
  if "rich_greenfield_needs_multiple_pages" in issues:
    lines.append("- Add every module/page from the original request with real UI sections and working handlers.")
  lines.append("Use write_file for new paths and str_replace for partial edits. Finish only when the app matches the brief.")
  return "\n".join(lines).strip()
