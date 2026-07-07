"""HTTP API for Worktual agent skills."""

from __future__ import annotations

try:
  from .skills_parts.helpers import (
    SkillSummary,
    build_skill_author_prompt,
    normalize_skill_name,
    prompt_has_explicit_skill_name,
    skill_description_from_prompt,
    skill_markdown,
    skill_name_from_prompt,
    strip_markdown_frontmatter,
  )
  from .skills_parts.payloads import (
    bootstrap_project_skills_payload,
    bootstrap_skills_payload,
    create_skill_payload,
    list_project_skills_payload,
    list_skills_payload,
  )
except ImportError:
  from backend.api.skills_parts.helpers import (
    SkillSummary,
    build_skill_author_prompt,
    normalize_skill_name,
    prompt_has_explicit_skill_name,
    skill_description_from_prompt,
    skill_markdown,
    skill_name_from_prompt,
    strip_markdown_frontmatter,
  )
  from backend.api.skills_parts.payloads import (
    bootstrap_project_skills_payload,
    bootstrap_skills_payload,
    create_skill_payload,
    list_project_skills_payload,
    list_skills_payload,
  )
