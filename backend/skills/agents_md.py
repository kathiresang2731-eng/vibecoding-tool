"""Project-level AGENTS.md bootstrap and context injection."""

from __future__ import annotations

from typing import Any

PROJECT_AGENTS_PATHS = (".worktual/AGENTS.md", "AGENTS.md")

DEFAULT_PROJECT_AGENTS_MD = """# Project Agents

## Conventions

- Prefer small, patch-first edits over full-file rewrites.
- Read relevant files before changing code.
- Keep `src/App.jsx` as a thin shell; put UI in components/pages.
- Match existing naming, imports, and styling patterns.

## Validation

- Generated artifacts must pass validation gates before commit.
- Fix gate failures before proposing new features.

## Memory

- Use episodic project memory and chat history for follow-up requests.
- Treat live project files as authoritative over older chat snippets.
"""


def find_project_agents_md(project_files: list[dict[str, Any]] | None) -> dict[str, Any] | None:
  if not isinstance(project_files, list):
    return None
  by_path = {
    str(item.get("path") or "").strip(): item
    for item in project_files
    if isinstance(item, dict) and str(item.get("path") or "").strip()
  }
  for path in PROJECT_AGENTS_PATHS:
    item = by_path.get(path)
    if isinstance(item, dict) and str(item.get("content") or "").strip():
      return {"path": path, "content": str(item.get("content") or "").strip()}
  return None


def build_project_agents_md_block(project_files: list[dict[str, Any]] | None) -> tuple[str, dict[str, Any]]:
  existing = find_project_agents_md(project_files)
  if existing:
    return (
      f"Project agent rules ({existing['path']}):\n{existing['content']}",
      {"path": existing["path"], "bootstrapped": False},
    )
  return (
    f"Project agent rules (default bootstrap for {PROJECT_AGENTS_PATHS[0]}):\n{DEFAULT_PROJECT_AGENTS_MD.strip()}",
    {"path": PROJECT_AGENTS_PATHS[0], "bootstrapped": True},
  )
