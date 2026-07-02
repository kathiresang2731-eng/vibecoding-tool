"""Format matched skills for LLM prompts."""

from __future__ import annotations

from .models import SkillSpec


def build_skills_prompt_block(skills: list[SkillSpec]) -> str:
    if not skills:
        return ""
    lines = [
        "## Active Worktual Skills",
        "",
        "The following skill instructions apply to this request because you explicitly invoked them. Follow them when relevant.",
        "",
    ]
    for skill in skills:
        lines.extend(
            [
                f"### Skill: {skill.name}",
                f"_{skill.description}_",
                "",
                skill.body.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip()


def build_skill_recommendation_block(
    *,
    selected_names: list[str],
    rejected: list[SkillSpec] | None = None,
    recommended: list[SkillSpec] | None = None,
    missing_names: list[str] | None = None,
    create_skill_suggestion: str = "",
    reason: str = "",
) -> str:
    if not selected_names and not missing_names:
        return ""
    lines = [
        "## Worktual Skill Selection Advisory",
        "",
        "The user explicitly selected a skill, but the skill selection must be validated before doing the task.",
        f"User selected: {', '.join('/' + name for name in selected_names) or 'none'}",
    ]
    if missing_names:
        lines.append(f"Missing skill(s): {', '.join('/' + name for name in missing_names)}")
    if rejected:
        lines.append("Rejected as not relevant to this task:")
        lines.extend(f"- /{skill.name}: {skill.description}" for skill in rejected)
    if recommended:
        lines.append("Recommended existing skill(s):")
        lines.extend(f"- /{skill.name}: {skill.description}" for skill in recommended[:3])
    if create_skill_suggestion:
        lines.append(f"Create-skill suggestion: `{create_skill_suggestion}`")
    if reason:
        lines.append(f"Reason: {reason}")
    lines.extend(
        [
            "",
            "Instruction:",
            "- Do not execute the original task with the irrelevant or missing selected skill.",
            "- Respond to the user and recommend the best existing skill if one is listed.",
            "- If no existing skill is listed, recommend creating a new skill using the create-skill suggestion.",
            "- Ask the user to confirm the recommended skill or create-skill action before continuing.",
        ]
    )
    return "\n".join(lines).strip()
