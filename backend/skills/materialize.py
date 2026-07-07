"""Materialize discovered skills into a linked project workspace."""

from __future__ import annotations

from pathlib import Path

from .discovery import discover_skills
from .manifest import write_project_skills_index_content

PROJECT_SKILL_PREFIX = ".worktual/skills"


def build_project_skill_materialize_files(
    *,
    workspace_root: Path | None = None,
    system_name: str | None = None,
) -> list[dict[str, str]]:
    skills = discover_skills(workspace_root, system_name=system_name)
    files: list[dict[str, str]] = []
    for skill in skills:
        if skill.scope == "project":
            continue
        try:
            content = skill.skill_md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        files.append(
            {
                "path": f"{PROJECT_SKILL_PREFIX}/{skill.name}/SKILL.md",
                "content": content,
            }
        )
    files.append(
        {
            "path": f"{PROJECT_SKILL_PREFIX}/skills.md",
            "content": write_project_skills_index_content(skills),
        }
    )
    return files


def build_user_home_skill_materialize_files(
    *,
    workspace_root: Path | None = None,
    system_name: str | None = None,
) -> list[dict[str, str]]:
    skills = discover_skills(workspace_root, system_name=system_name)
    files: list[dict[str, str]] = []
    for skill in skills:
        if skill.scope == "project":
            continue
        try:
            content = skill.skill_md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        files.append(
            {
                "path": f"{skill.name}/SKILL.md",
                "content": content,
            }
        )
    files.append(
        {
            "path": "skills.md",
            "content": write_project_skills_index_content(skills),
        }
    )
    return files
