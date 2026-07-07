"""Generate ~/.worktual-skills/skills.md index (Cursor/Codex-style catalog)."""

from __future__ import annotations

from pathlib import Path

from .discovery import discover_skills
from .settings import user_skills_home


def write_project_skills_index_content(skills: list) -> str:
    lines = [
        "# Worktual Project Skills",
        "",
        "Agent skills installed in this workspace (`.worktual/skills/`).",
        "Compatible with Cursor/Codex `SKILL.md` layout.",
        "",
        "## Installed skills",
        "",
    ]
    if not skills:
        lines.append("_No skills installed yet._")
    else:
        lines.extend(["| Skill | Scope | Description |", "| --- | --- | --- |"])
        for skill in skills:
            description = skill.description.replace("|", "\\|").replace("\n", " ")
            if len(description) > 160:
                description = description[:157] + "..."
            lines.append(f"| `{skill.name}` | {skill.scope} | {description} |")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_skills_index(
    home: Path | None = None,
    *,
    workspace_root: Path | None = None,
    system_name: str | None = None,
) -> Path:
    skills_home = home or user_skills_home(system_name)
    skills_home.mkdir(parents=True, exist_ok=True)
    skills = discover_skills(workspace_root, system_name=system_name)
    index_path = skills_home / "skills.md"

    lines = [
        "# Worktual Skills",
        "",
        "Auto-generated index of agent skills available on this machine.",
        "Individual skills live in `skill-name/SKILL.md` folders (Cursor/Codex-compatible).",
        "",
        "## Usage",
        "",
        "- **Opt-in only**: type `/skill-name` in chat (example: `/greenfield-website`), `@skill:name`, or reference `.worktual/skills/skill-name`.",
        "- Skills are never applied automatically without explicit user permission.",
        "- **Project skills**: add `.worktual/skills/<name>/SKILL.md` inside a linked repo.",
        "",
        f"**User skills home:** `{skills_home}`",
        "",
        "## Installed skills",
        "",
    ]

    if not skills:
        lines.extend(
            [
                "_No skills discovered yet. The app will seed defaults on first bootstrap._",
                "",
            ]
        )
    else:
        lines.extend(["| Skill | Scope | Description |", "| --- | --- | --- |"])
        for skill in skills:
            description = skill.description.replace("|", "\\|").replace("\n", " ")
            if len(description) > 160:
                description = description[:157] + "..."
            lines.append(f"| `{skill.name}` | {skill.scope} | {description} |")
        lines.append("")

    lines.extend(
        [
            "## Layout",
            "",
            "```text",
            f"{skills_home}/",
            "  skills.md                 # this index",
            "  greenfield-website/",
            "    SKILL.md",
            "  session-code-edit/",
            "    SKILL.md",
            "```",
            "",
        ]
    )

    index_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return index_path
