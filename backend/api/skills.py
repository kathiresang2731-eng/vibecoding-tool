"""HTTP API for Worktual agent skills."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

try:
    from ..skills.bootstrap import ensure_user_skills_home
    from ..skills.discovery import discover_skills
    from ..skills.manifest import write_project_skills_index_content, write_skills_index
    from ..skills.materialize import (
        PROJECT_SKILL_PREFIX,
        build_project_skill_materialize_files,
        build_user_home_skill_materialize_files,
    )
    from ..skills.paths import discovery_roots
    from ..skills.settings import user_skills_home
    from ..skills.system_name import resolve_system_name
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


def list_skills_payload(
    workspace_root: str | None = None,
    *,
    project_files: list[dict] | None = None,
    system_name: str | None = None,
    local_path: str | None = None,
) -> dict[str, Any]:
    root = _workspace_root(workspace_root)
    resolved_name = _resolved_system_name(
        system_name=system_name,
        workspace_root=root,
        local_path=local_path or workspace_root,
    )
    home = user_skills_home(resolved_name)
    skills = _summaries(root, project_files=project_files, system_name=resolved_name)
    return {
        "system_name": resolved_name,
        "home": str(home),
        "index": str(home / "skills.md"),
        "roots": [{"path": str(path), "scope": scope} for path, scope in discovery_roots(root, system_name=resolved_name)],
        "skills": [skill.model_dump() for skill in skills],
        "count": len(skills),
    }


def list_project_skills_payload(
    project_id: str,
    store: Any,
    user: Any,
    *,
    workspace_root: str | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id, user)
    if not project:
        raise ValueError("Project not found.")

    linked_root = _workspace_root(str(project.get("local_path") or "").strip() or None)
    requested_root = _workspace_root(workspace_root)
    root = linked_root or requested_root
    resolved_name = _resolved_system_name(
        system_name=system_name,
        workspace_root=root,
        local_path=str(project.get("local_path") or "").strip() or workspace_root,
    )
    project_files = store.list_files(project_id, user)
    return list_skills_payload(
        str(root) if root else None,
        project_files=project_files,
        system_name=resolved_name,
        local_path=str(project.get("local_path") or "").strip() or workspace_root,
    )


def bootstrap_skills_payload(
    workspace_root: str | None = None,
    *,
    system_name: str | None = None,
) -> dict[str, Any]:
    root = _workspace_root(workspace_root)
    resolved_name = _resolved_system_name(system_name=system_name, workspace_root=root, local_path=workspace_root)
    home, created = ensure_user_skills_home(workspace_root=root, system_name=resolved_name)
    write_skills_index(home, workspace_root=root, system_name=resolved_name)
    skills = _summaries(root, system_name=resolved_name)
    materialize_files = build_project_skill_materialize_files(workspace_root=root, system_name=resolved_name)
    user_home_files = build_user_home_skill_materialize_files(workspace_root=root, system_name=resolved_name)
    return {
        "system_name": resolved_name,
        "home": str(home),
        "index": str(home / "skills.md"),
        "created_defaults": created.get("created_defaults", []),
        "synced_from_repo": created.get("synced_from_repo", []),
        "skills": [skill.model_dump() for skill in skills],
        "count": len(skills),
        "materialize_files": materialize_files,
        "user_home_files": user_home_files,
    }


def create_skill_payload(
    prompt: str,
    *,
    workspace_root: str | None = None,
    system_name: str | None = None,
    model_provider: Any | None = None,
    project_id: str | None = None,
    store: Any | None = None,
    user: Any | None = None,
) -> dict[str, Any]:
    root = _workspace_root(workspace_root)
    resolved_name = _resolved_system_name(system_name=system_name, workspace_root=root, local_path=workspace_root)
    home, _created = ensure_user_skills_home(workspace_root=root, system_name=resolved_name)
    name = skill_name_from_prompt(prompt)
    description = skill_description_from_prompt(prompt, name)
    model_authored = model_provider is not None
    gap_analysis = ""
    if model_provider is not None:
        name, description, content, gap_analysis = llm_skill_markdown(name, description, prompt, model_provider)
    else:
        content = skill_markdown(name, description, prompt)
    skill_dir = home / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    index = write_skills_index(home, workspace_root=root, system_name=resolved_name)
    project_file = {
        "path": f"{PROJECT_SKILL_PREFIX}/{name}/SKILL.md",
        "content": content,
    }
    project_saved = False
    saved_project_file = None
    saved_project_index = None
    project_index_file = None
    project_files_for_discovery: list[dict] | None = None
    if project_id and store is not None and user is not None:
        saved_project_file = store.upsert_file(project_id, user, path=project_file["path"], content=project_file["content"])
        project_saved = True
        if hasattr(store, "list_files"):
            project_files_for_discovery = store.list_files(project_id, user)
        else:
            project_files_for_discovery = [saved_project_file]
        discovered = _summaries(root, project_files=project_files_for_discovery, system_name=resolved_name)
        project_index_file = {
            "path": f"{PROJECT_SKILL_PREFIX}/skills.md",
            "content": write_project_skills_index_content(discovered),
        }
        saved_project_index = store.upsert_file(
            project_id,
            user,
            path=project_index_file["path"],
            content=project_index_file["content"],
        )
    user_home_files = build_user_home_skill_materialize_files(workspace_root=root, system_name=resolved_name)
    return {
        "system_name": resolved_name,
        "name": name,
        "description": description,
        "gap_analysis": gap_analysis,
        "path": str(skill_md),
        "index": str(index),
        "home": str(home),
        "project_file": project_file,
        "project_index_file": project_index_file,
        "project_saved": project_saved,
        "saved_project_file": saved_project_file,
        "saved_project_index": saved_project_index,
        "user_home_files": user_home_files,
        "model_authored": model_authored,
        "message": f"Created skill /{name} at {skill_md}",
    }


def _safe_add_project_event(store: Any, project_id: str, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    try:
        store.add_event(project_id, user_id, event_type, payload)
    except Exception:
        # Skill files are already persisted; event logging must not fail bootstrap.
        pass


def bootstrap_project_skills_payload(
    project_id: str,
    store: Any,
    user: Any,
    *,
    workspace_root: str | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id, user)
    if not project:
        raise ValueError("Project not found.")

    linked_root = _workspace_root(str(project.get("local_path") or "").strip() or None)
    requested_root = _workspace_root(workspace_root)
    root = linked_root or requested_root
    resolved_name = _resolved_system_name(
        system_name=system_name,
        workspace_root=root,
        local_path=str(project.get("local_path") or "").strip() or workspace_root,
    )

    payload = bootstrap_skills_payload(
        str(root) if root else None,
        system_name=resolved_name,
    )
    materialize_files = payload.get("materialize_files") or []
    imported_paths: list[str] = []
    for file_item in materialize_files:
        path = str(file_item.get("path") or "").strip()
        content = file_item.get("content")
        if not path or not isinstance(content, str):
            continue
        store.upsert_file(project_id, user, path=path, content=content, emit_event=False)
        imported_paths.append(path)

    if linked_root and materialize_files:
        try:
            try:
                from ..local_workspace.io import write_local_project_files
            except ImportError:
                from local_workspace.io import write_local_project_files
            write_local_project_files(linked_root, materialize_files)
        except Exception:
            pass

    if imported_paths:
        _safe_add_project_event(
            store,
            project_id,
            user.id,
            "skills.bootstrapped",
            {
                "count": len(imported_paths),
                "paths": imported_paths[:50],
                "system_name": resolved_name,
            },
        )

    project_files = store.list_files(project_id, user)
    payload["project_id"] = project_id
    payload["imported_count"] = len(imported_paths)
    payload["imported_paths"] = imported_paths
    payload["skills"] = [
        skill.model_dump()
        for skill in _summaries(root, project_files=project_files, system_name=resolved_name)
    ]
    payload["count"] = len(payload["skills"])
    return payload
