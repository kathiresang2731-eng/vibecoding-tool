from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

try:
  from ...skills.bootstrap import ensure_user_skills_home
  from ...skills.discovery import discover_skills
  from ...skills.manifest import write_project_skills_index_content, write_skills_index
  from ...skills.materialize import (
    PROJECT_SKILL_PREFIX,
    build_project_skill_materialize_files,
    build_user_home_skill_materialize_files,
  )
  from ...skills.paths import discovery_roots
  from ...skills.settings import user_skills_home
  from ...skills.system_name import resolve_system_name
except ImportError:
  from skills.bootstrap import ensure_user_skills_home
  from skills.discovery import discover_skills
  from skills.manifest import write_project_skills_index_content, write_skills_index
  from skills.materialize import (
    PROJECT_SKILL_PREFIX,
    build_project_skill_materialize_files,
    build_user_home_skill_materialize_files,
  )
  from skills.paths import discovery_roots
  from skills.settings import user_skills_home
  from skills.system_name import resolve_system_name


class SkillSummary(BaseModel):
  name: str
  description: str
  scope: str
  path: str
  root: str
  paths: list[str] = Field(default_factory=list)
  disable_auto: bool = False


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SKILL_AUTHOR_SYSTEM_INSTRUCTION = (
  "You are Worktual's skill authoring agent. Create practical Cursor/Worktual agent skills, "
  "not generic summaries. Return only valid JSON that matches the requested shape."
)


def normalize_skill_name(value: str) -> str:
  cleaned = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")
  cleaned = re.sub(r"-{2,}", "-", cleaned)
  if not cleaned or not _SKILL_NAME_RE.match(cleaned):
    raise ValueError("Skill name must be lowercase letters, numbers, and hyphens.")
  return cleaned


def skill_name_from_prompt(prompt: str) -> str:
  text = str(prompt or "").strip()
  explicit = re.search(r"(?:called|named|name)\s+[`'\"]?([a-zA-Z0-9][a-zA-Z0-9_-]{0,63})", text, re.IGNORECASE)
  if explicit:
    return normalize_skill_name(explicit.group(1))
  without_command = re.sub(r"^/create-skill\s*", "", text, flags=re.IGNORECASE).strip()
  words = re.findall(r"[a-zA-Z0-9]+", without_command)
  stop = {"create", "skill", "for", "to", "that", "which", "when", "use", "using", "agent", "workflow"}
  selected = [word for word in words if word.lower() not in stop][:4]
  if not selected:
    selected = ["custom", "skill"]
  return normalize_skill_name("-".join(selected))


def prompt_has_explicit_skill_name(prompt: str) -> bool:
  text = str(prompt or "").strip()
  return bool(re.search(r"(?:called|named|name)\s+[`'\"]?([a-zA-Z0-9][a-zA-Z0-9_-]{0,63})", text, re.IGNORECASE))


def skill_description_from_prompt(prompt: str, name: str) -> str:
  text = re.sub(r"^/create-skill\s*", "", str(prompt or "").strip(), flags=re.IGNORECASE).strip()
  text = text or f"Use this skill for the {name.replace('-', ' ')} workflow."
  return text[:240]


def skill_markdown(name: str, description: str, prompt: str) -> str:
  return (
    "---\n"
    f"name: {name}\n"
    f"description: {description}\n"
    "---\n\n"
    f"# {name.replace('-', ' ').title()}\n\n"
    "## Purpose\n\n"
    f"{description}\n\n"
    "## Workflow\n\n"
    "1. Read the user's request and relevant project context.\n"
    "2. Follow this saved workflow or instruction:\n\n"
    f"{prompt.strip()}\n\n"
    "3. If the request asks about a topic, technology, product, error, library, market, or current best practice, use web search to gather up-to-date information before answering.\n"
    "4. Provide detailed information with proper analysis: explain the background, key concepts, current state, tradeoffs, risks, implementation steps, and practical recommendations.\n"
    "5. Compare alternatives when useful and call out assumptions, limitations, and where the information may change over time.\n"
    "6. Keep code or project changes focused, and verify the result when possible.\n"
  )


def build_skill_author_prompt(name: str, description: str, prompt: str) -> str:
  explicit_name = prompt_has_explicit_skill_name(prompt)
  return (
    "Create a Worktual agent skill from the user's request. The user may provide the skill as plain text, rough notes, requirements, or an incomplete workflow.\n\n"
    f"Initial skill name: {name}\n"
    f"Name was explicitly provided by user: {'yes' if explicit_name else 'no'}\n"
    f"Initial description: {description}\n"
    f"User request:\n{prompt.strip()}\n\n"
    "First do a gap analysis of the provided skill text: identify missing scope, unclear triggers, missing steps, missing output expectations, verification gaps, tool/web-search needs, and safety or quality risks.\n\n"
    "Return JSON with these string fields:\n"
    "- name: a concise lowercase hyphenated skill name, max 64 characters. If the user explicitly named the skill, keep that meaning. If not, propose the best name from the skill text.\n"
    "- description: a concise one-sentence skill description, max 220 characters.\n"
    "- gap_analysis: a concise markdown bullet list of gaps found and how you addressed them.\n"
    "- body_markdown: markdown content for SKILL.md after frontmatter. Do not include YAML frontmatter.\n\n"
    "The body_markdown must be detailed and actionable. Include:\n"
    "- a clear title\n"
    "- purpose and when to use the skill\n"
    "- a Gap Analysis section based on gap_analysis\n"
    "- step-by-step workflow\n"
    "- requirements to use web search for current facts, libraries, products, errors, best practices, market data, or recent changes\n"
    "- analysis expectations: background, key concepts, current state, tradeoffs, risks, implementation steps, recommendations, assumptions, limitations, and citations/links when web research is used\n"
    "- output format guidance for the final answer\n"
    "- verification or follow-up steps when relevant\n"
  )


def strip_markdown_frontmatter(value: str) -> str:
  text = str(value or "").strip()
  if text.startswith("---"):
    parts = text.split("---", 2)
    if len(parts) == 3:
      text = parts[2].strip()
  return text


def llm_skill_markdown(name: str, description: str, prompt: str, model_provider: Any) -> tuple[str, str, str, str]:
  response = model_provider.generate_json_with_search(
    build_skill_author_prompt(name, description, prompt),
    system_instruction=_SKILL_AUTHOR_SYSTEM_INSTRUCTION,
    trace_label="create_skill_llm_author",
  )
  if not isinstance(response, dict):
    raise ValueError("Skill authoring model returned an invalid response.")
  generated_name = name
  if not prompt_has_explicit_skill_name(prompt):
    generated_name = normalize_skill_name(str(response.get("name") or name))
  generated_description = str(response.get("description") or description).strip()[:240]
  gap_analysis = str(response.get("gap_analysis") or "").strip()
  body = strip_markdown_frontmatter(str(response.get("body_markdown") or "").strip())
  if not generated_description or len(body) < 120:
    raise ValueError("Skill authoring model returned an incomplete skill.")
  if "gap analysis" not in body.lower():
    body = (
      f"# {generated_name.replace('-', ' ').title()}\n\n"
      "## Gap Analysis\n\n"
      f"{gap_analysis or '- Reviewed the provided skill text and filled missing workflow, output, verification, and research requirements.'}\n\n"
      f"{body.lstrip('#').strip()}\n"
    )
  if "web search" not in body.lower():
    body += (
      "\n\n## Research Requirements\n\n"
      "- Use web search whenever the user asks about current facts, libraries, products, errors, best practices, market data, or recent changes.\n"
      "- Include relevant source links or citations when web research informs the answer.\n"
    )
  content = (
    "---\n"
    f"name: {generated_name}\n"
    f"description: {generated_description}\n"
    "---\n\n"
    f"{body.strip()}\n"
  )
  return generated_name, generated_description, content, gap_analysis


def _workspace_root(value: str | None) -> Path | None:
  if not value or not str(value).strip():
    return None
  root = Path(str(value).strip()).expanduser()
  return root if root.is_dir() else None


def _resolved_system_name(
  *,
  system_name: str | None,
  workspace_root: Path | None,
  local_path: str | None = None,
) -> str:
  return resolve_system_name(
    explicit=system_name,
    workspace_root=workspace_root,
    local_path=local_path,
  )


def _summaries(
  workspace_root: Path | None = None,
  *,
  project_files: list[dict] | None = None,
  system_name: str | None = None,
) -> list[SkillSummary]:
  return [
    SkillSummary(
      name=skill.name,
      description=skill.description,
      scope=skill.scope,
      path=str(skill.skill_md_path),
      root=str(skill.root_dir),
      paths=list(skill.paths),
      disable_auto=skill.disable_auto,
    )
    for skill in discover_skills(workspace_root, project_files=project_files, system_name=system_name)
  ]
