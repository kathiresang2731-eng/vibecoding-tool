"""Select relevant skills for a user request."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import discover_skills
from .models import SkillSpec
from .settings import skills_enabled, skills_max_injected

_EXPLICIT_SKILL_RE = re.compile(r"(?:^|\s)/([a-z0-9][a-z0-9-]{0,63})(?:\s|$)")
_AT_SKILL_RE = re.compile(r"@skill:([a-z0-9][a-z0-9-]{0,63})", re.IGNORECASE)
_PROJECT_SKILL_PATH_RE = re.compile(
    r"\.worktual/skills/([a-z0-9][a-z0-9-]{0,63})",
    re.IGNORECASE,
)
_WORKTUAL_SKILLS_OPT_IN_RE = re.compile(r"\.worktual\s*/?\s*skills\b", re.IGNORECASE)
_CREATE_SKILL_COMMAND_RE = re.compile(r"^/create-skill(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class SkillResolution:
    selected: list[SkillSpec] = field(default_factory=list)
    explicit_names: list[str] = field(default_factory=list)
    missing_names: list[str] = field(default_factory=list)
    rejected: list[SkillSpec] = field(default_factory=list)
    recommended: list[SkillSpec] = field(default_factory=list)
    create_skill_suggestion: str = ""
    reason: str = ""

    @property
    def has_explicit_mismatch(self) -> bool:
        return bool(self.explicit_names and (self.rejected or self.missing_names) and not self.selected)

    @property
    def opted_in(self) -> bool:
        return bool(self.explicit_names or self.selected)


def user_opted_into_skills(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    if _CREATE_SKILL_COMMAND_RE.match(text):
        return True
    if _explicit_skill_names(text):
        return True
    if _WORKTUAL_SKILLS_OPT_IN_RE.search(text):
        return True
    return False


def _explicit_skill_names(message: str) -> list[str]:
    names: list[str] = []
    for pattern in (_EXPLICIT_SKILL_RE, _AT_SKILL_RE, _PROJECT_SKILL_PATH_RE):
        for match in pattern.finditer(message):
            name = match.group(1).lower()
            if name in {"create-skill", "skills"}:
                continue
            if name not in names:
                names.append(name)
    return names


def _message_without_skill_invocations(message: str) -> str:
    text = _EXPLICIT_SKILL_RE.sub(" ", str(message or " "))
    text = _AT_SKILL_RE.sub(" ", text)
    text = _PROJECT_SKILL_PATH_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _path_matches_glob(rel_path: str, pattern: str) -> bool:
    from fnmatch import fnmatch

    normalized = rel_path.replace("\\", "/")
    pat = pattern.replace("\\", "/")
    return fnmatch(normalized, pat) or fnmatch(normalized, f"**/{pat}")


def _skill_matches_workspace(skill: SkillSpec, workspace_files: list[str]) -> bool:
    if not skill.paths:
        return True
    if not workspace_files:
        return True
    for pattern in skill.paths:
        if pattern in {"**/*", "**", "*"}:
            return True
        for rel in workspace_files:
            if _path_matches_glob(rel, pattern):
                return True
    return False


def _score_skill(skill: SkillSpec, message: str) -> float:
    lowered = message.lower()
    score = 0.0
    for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", skill.description.lower()):
        if token in lowered:
            score += 1.5
    for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", skill.name.replace("-", " ").lower()):
        if token in lowered:
            score += 2.0
    boosts = {
        "website": ("greenfield-website", "frontend", "react", "vite"),
        "site": ("greenfield-website", "frontend", "react", "vite"),
        "build": ("greenfield-website",),
        "shop": ("greenfield-website", "react"),
        "store": ("greenfield-website", "react"),
        "e-commerce": ("greenfield-website", "react"),
        "edit": ("session-code-edit", "edit"),
        "fix": ("session-code-edit", "debug"),
        "local": ("worktual-local-workspace", "local"),
        "folder": ("worktual-local-workspace", "local"),
        "deploy": ("deploy",),
    }
    for keyword, skill_hints in boosts.items():
        if keyword in lowered:
            for hint in skill_hints:
                if hint in skill.name:
                    score += 3.0
    return score


def _create_skill_suggestion(message: str) -> str:
    cleaned = _message_without_skill_invocations(message)
    words = re.findall(r"[a-zA-Z0-9]+", cleaned)
    stop = {"create", "skill", "for", "to", "that", "which", "when", "use", "using", "agent", "workflow", "please"}
    selected = [word.lower() for word in words if word.lower() not in stop][:4] or ["custom", "task"]
    name = re.sub(r"-{2,}", "-", "-".join(selected)).strip("-")[:64] or "custom-task"
    return f"/create-skill named {name} for {cleaned or 'this task'}"


def resolve_skill_resolution(
    message: str,
    *,
    workspace_root: Path | None = None,
    workspace_files: list[str] | None = None,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
) -> SkillResolution:
    combined = str(message or "").strip()
    if not skills_enabled() or _CREATE_SKILL_COMMAND_RE.match(combined):
        return SkillResolution()

    if not user_opted_into_skills(combined):
        return SkillResolution(
            reason=(
                "Skills are opt-in only. Invoke a skill with /skill-name, @skill:name, "
                "or .worktual/skills/skill-name when you want to use project skills."
            ),
        )

    catalog = discover_skills(workspace_root, project_files=project_files, system_name=system_name)
    if not catalog:
        return SkillResolution(create_skill_suggestion=_create_skill_suggestion(message), reason="No skills are installed yet.")

    task_message = _message_without_skill_invocations(combined)
    explicit = _explicit_skill_names(combined)
    if _WORKTUAL_SKILLS_OPT_IN_RE.search(combined) and not explicit:
        return SkillResolution(
            reason=(
                "You mentioned .worktual skills. Pick a skill to apply with /skill-name "
                "(example: /greenfield-website) or reference .worktual/skills/skill-name."
            ),
        )
    files = workspace_files or []
    by_name = {skill.name: skill for skill in catalog}

    scored: list[tuple[float, SkillSpec]] = []
    for skill in catalog:
        if not _skill_matches_workspace(skill, files):
            continue
        score = _score_skill(skill, task_message)
        if score > 0:
            scored.append((score, skill))
    scored.sort(key=lambda item: (-item[0], item[1].name))

    if explicit:
        missing = [name for name in explicit if name not in by_name]
        selected: list[SkillSpec] = []
        rejected: list[SkillSpec] = []
        for name in explicit:
            skill = by_name.get(name)
            if skill is None:
                continue
            workspace_ok = _skill_matches_workspace(skill, files)
            if workspace_ok:
                selected.append(skill)
            else:
                rejected.append(skill)
        if selected:
            return SkillResolution(
                selected=selected[:skills_max_injected()],
                explicit_names=explicit,
                missing_names=missing,
                reason="The explicitly selected skill will be used for this request.",
            )
        recommended = [skill for _score, skill in scored if skill.name not in explicit and not skill.disable_auto][:3]
        return SkillResolution(
            explicit_names=explicit,
            missing_names=missing,
            rejected=rejected,
            recommended=recommended,
            create_skill_suggestion=_create_skill_suggestion(task_message),
            reason="The selected skill does not appear relevant to the requested task.",
        )

    return SkillResolution(
        reason="No skill was explicitly selected for this request.",
    )


def resolve_skills_for_request(
    message: str,
    *,
    workspace_root: Path | None = None,
    workspace_files: list[str] | None = None,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
) -> list[SkillSpec]:
    return resolve_skill_resolution(
        message,
        workspace_root=workspace_root,
        workspace_files=workspace_files,
        project_files=project_files,
        system_name=system_name,
    ).selected
