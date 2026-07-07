"""Discover SKILL.md files under configured roots."""

from __future__ import annotations

import re
from pathlib import Path

from .models import SkillSpec
from .parser import parse_skill_md, parse_skill_text
from .paths import discovery_roots

_PROJECT_SKILL_PATH_RE = re.compile(
    r"^\.(?:worktual|cursor|agents)/skills/([^/]+)/SKILL\.md$",
    re.IGNORECASE,
)


def discover_skills(
    workspace_root: Path | None = None,
    *,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
) -> list[SkillSpec]:
    by_name: dict[str, SkillSpec] = {}
    _ALLOWED_DOT_DIRS = {".worktual", ".worktual-skills", ".cursor", ".agents"}
    for root, scope in discovery_roots(workspace_root, system_name=system_name):
        for skill_md in sorted(root.rglob("SKILL.md")):
            if any(part.startswith(".") and part not in _ALLOWED_DOT_DIRS for part in skill_md.parts):
                continue
            spec = parse_skill_md(skill_md, scope=scope)
            if spec is None:
                continue
            existing = by_name.get(spec.name)
            if existing is None or _scope_rank(spec.scope) >= _scope_rank(existing.scope):
                by_name[spec.name] = spec
    for spec in _discover_skills_from_project_files(project_files or []):
        existing = by_name.get(spec.name)
        if existing is None or _scope_rank(spec.scope) >= _scope_rank(existing.scope):
            by_name[spec.name] = spec
    return sorted(by_name.values(), key=lambda item: item.name)


def _discover_skills_from_project_files(files: list[dict]) -> list[SkillSpec]:
    discovered: list[SkillSpec] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip().replace("\\", "/")
        if not path or not _PROJECT_SKILL_PATH_RE.match(path):
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        spec = parse_skill_text(path, content, scope="project")
        if spec is not None:
            discovered.append(spec)
    return discovered


def _scope_rank(scope: str) -> int:
    return {"user": 3, "project": 2, "bundled": 1}.get(scope, 0)
