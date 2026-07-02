"""Resolve and format skills for generation requests."""

from __future__ import annotations

from pathlib import Path

from .bootstrap import ensure_user_skills_home
from .injector import build_skills_prompt_block
from .matcher import SkillResolution, resolve_skill_resolution, resolve_skills_for_request, user_opted_into_skills
from .models import SkillSpec
from .settings import user_skills_home
from .system_name import resolve_system_name


def resolve_matched_skills(
    message: str,
    *,
    workspace_root: Path | None = None,
    workspace_files: list[str] | None = None,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
    local_path: str | Path | None = None,
) -> list[SkillSpec]:
    resolved_name = resolve_system_name(
        explicit=system_name,
        workspace_root=workspace_root,
        local_path=local_path or workspace_root,
    )
    if user_opted_into_skills(message):
        try:
            ensure_user_skills_home(system_name=resolved_name)
        except OSError:
            # Skills are advisory; an unwritable user-skill directory must not block generation.
            pass
    return resolve_skills_for_request(
        message,
        workspace_root=workspace_root,
        workspace_files=workspace_files,
        project_files=project_files,
        system_name=resolved_name,
    )


def resolve_skill_request(
    message: str,
    *,
    workspace_root: Path | None = None,
    workspace_files: list[str] | None = None,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
    local_path: str | Path | None = None,
) -> SkillResolution:
    resolved_name = resolve_system_name(
        explicit=system_name,
        workspace_root=workspace_root,
        local_path=local_path or workspace_root,
    )
    if user_opted_into_skills(message):
        try:
            ensure_user_skills_home(system_name=resolved_name)
        except OSError:
            pass
    return resolve_skill_resolution(
        message,
        workspace_root=workspace_root,
        workspace_files=workspace_files,
        project_files=project_files,
        system_name=resolved_name,
    )


def skills_home_path(system_name: str | None = None) -> str:
    return str(user_skills_home(system_name))
