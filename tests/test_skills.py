"""Tests for Worktual agent skills bootstrap and matching."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from skills.bootstrap import ensure_user_skills_home
from skills.discovery import discover_skills
from skills.manifest import write_skills_index
from skills.matcher import resolve_skill_resolution, resolve_skills_for_request


@pytest.fixture()
def skills_home(tmp_path, monkeypatch):
    base = tmp_path / "skills-home"
    monkeypatch.setenv("WORKTUAL_SKILLS_DIR", str(base))
    return base / "vectone"


def test_bootstrap_creates_skills_md_and_defaults(skills_home):
    home, created = ensure_user_skills_home(system_name="vectone")
    assert home == skills_home
    assert (home / "skills.md").is_file()
    assert "greenfield-website" in created["created_defaults"]
    assert (home / "greenfield-website" / "SKILL.md").is_file()
    text = (home / "greenfield-website" / "SKILL.md").read_text(encoding="utf-8")
    assert "120 lines" not in text
    assert "1000+ lines" in text


def test_bootstrap_refreshes_legacy_greenfield_skill(skills_home):
    legacy = skills_home / "greenfield-website" / "SKILL.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        """---
name: greenfield-website
description: Legacy
---
# Greenfield Website

5. Keep each codegen step under 3 files and 120 lines for valid JSON.
""",
        encoding="utf-8",
    )

    home, created = ensure_user_skills_home(system_name="vectone")
    assert home == skills_home
    text = legacy.read_text(encoding="utf-8")
    assert "120 lines" not in text
    assert "1000+ lines" in text
    assert "greenfield-website" in created.get("refreshed_defaults", [])


def test_skills_index_lists_discovered_skills(skills_home):
    ensure_user_skills_home(system_name="vectone")
    index = write_skills_index(skills_home, system_name="vectone")
    text = index.read_text(encoding="utf-8")
    assert "# Worktual Skills" in text
    assert "greenfield-website" in text


def test_explicit_skill_invocation(skills_home):
    ensure_user_skills_home(system_name="vectone")
    matched = resolve_skills_for_request("Please /greenfield-website for a new shop")
    assert [skill.name for skill in matched] == ["greenfield-website"]


def test_irrelevant_explicit_skill_recommends_better_existing_skill(skills_home):
    ensure_user_skills_home(system_name="vectone")
    from skills.matcher import resolve_skill_resolution

    resolution = resolve_skill_resolution("Please /worktual-local-workspace build a new website for animals", system_name="vectone")
    assert [skill.name for skill in resolution.selected] == ["worktual-local-workspace"]
    assert not resolution.has_explicit_mismatch


def test_irrelevant_explicit_skill_recommends_create_skill_when_no_match(skills_home):
    ensure_user_skills_home(system_name="vectone")
    from skills.matcher import resolve_skill_resolution

    resolution = resolve_skill_resolution("Please /greenfield-website analyze vector database ranking", system_name="vectone")
    assert [skill.name for skill in resolution.selected] == ["greenfield-website"]
    assert not resolution.has_explicit_mismatch


def test_local_workspace_skill_matches_linked_path_prompt(skills_home, tmp_path):
    ensure_user_skills_home(system_name="vectone")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "App.jsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
    matched = resolve_skills_for_request(
        "sync generated files to my local folder using /worktual-local-workspace",
        workspace_root=workspace,
        workspace_files=["src/App.jsx"],
    )
    assert any(skill.name == "worktual-local-workspace" for skill in matched)


def test_website_prompt_without_explicit_skill_uses_no_skills(skills_home):
    ensure_user_skills_home(system_name="vectone")
    matched = resolve_skills_for_request("Build a modern website for a coffee shop with hero and menu sections")
    assert matched == []
    resolution = resolve_skill_resolution("Update the landing page hero section and footer")
    assert resolution.selected == []
    assert "opt-in" in resolution.reason.lower()


def test_worktual_skills_path_invocation(skills_home):
    ensure_user_skills_home(system_name="vectone")
    matched = resolve_skills_for_request("Follow .worktual/skills/greenfield-website to build a shop")
    assert [skill.name for skill in matched] == ["greenfield-website"]


def test_worktual_skills_mention_without_skill_name_does_not_apply(skills_home):
    ensure_user_skills_home(system_name="vectone")
    resolution = resolve_skill_resolution("Use .worktual skills to improve the hero section")
    assert resolution.selected == []
    assert "pick a skill" in resolution.reason.lower()


def test_project_skills_discovered_from_worktual_folder(skills_home, tmp_path):
    ensure_user_skills_home(system_name="vectone")
    workspace = tmp_path / "repo"
    project_skill = workspace / ".worktual" / "skills" / "team-style"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        """---
name: team-style
description: Follow the team React style guide for this repository.
paths: src/**
---
# Team style
""",
        encoding="utf-8",
    )
    names = {skill.name for skill in discover_skills(workspace)}
    assert "team-style" in names


def test_project_skills_discovered_from_imported_files(skills_home):
    ensure_user_skills_home(system_name="vectone")
    files = [
        {
            "path": ".worktual/skills/greenfield-website/SKILL.md",
            "content": """---
name: greenfield-website
description: Build a new React website from scratch in this browser workspace.
paths: src/**
---
# Greenfield
""",
        }
    ]
    names = {skill.name for skill in discover_skills(project_files=files)}
    assert "greenfield-website" in names


def test_materialize_files_include_project_skill_paths(skills_home):
    ensure_user_skills_home(system_name="vectone")
    from skills.materialize import build_project_skill_materialize_files, build_user_home_skill_materialize_files

    files = build_project_skill_materialize_files(system_name="vectone")
    paths = {item["path"] for item in files}
    assert ".worktual/skills/greenfield-website/SKILL.md" in paths
    assert ".worktual/skills/skills.md" in paths

    home_files = build_user_home_skill_materialize_files(system_name="vectone")
    home_paths = {item["path"] for item in home_files}
    assert "greenfield-website/SKILL.md" in home_paths
    assert "skills.md" in home_paths


def test_user_skills_home_falls_back_when_legacy_home_not_writable(tmp_path, monkeypatch):
    import skills.settings as settings

    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    legacy = fake_home / ".worktual-skills"
    legacy.mkdir()
    os.chmod(legacy, 0o555)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("WORKTUAL_SKILLS_DIR", str(tmp_path / "configured-skills"))

    writable = settings.user_skills_home("rahul")
    assert writable == (tmp_path / "configured-skills" / "rahul")
    home, _created = ensure_user_skills_home(system_name="rahul")
    assert home == writable
    assert (home / "skills.md").is_file()


def test_derive_system_name_from_home_documents_path():
    from skills.system_name import derive_system_name_from_path, resolve_system_name

    assert derive_system_name_from_path("/home/kathir/Documents/myproject") == "kathir"
    assert resolve_system_name(local_path="/home/rahul/documents/site") == "rahul"


def test_resolve_system_name_prefers_workspace_path_over_explicit():
    from skills.system_name import resolve_system_name

    assert (
        resolve_system_name(
            explicit="vectone",
            workspace_root="/home/kathir/Documents/myproject",
        )
        == "kathir"
    )


def test_list_project_skills_payload_includes_project_store_skills(skills_home):
    from api.skills import list_project_skills_payload

    class FakeStore:
        def get_project(self, project_id, user):
            return {"id": project_id, "local_path": ""}

        def list_files(self, project_id, user):
            return [
                {
                    "path": ".worktual/skills/custom-skill/SKILL.md",
                    "content": """---
name: custom-skill
description: A project-only skill saved in the backend store.
---
# Custom skill
""",
                }
            ]

    payload = list_project_skills_payload("project-1", FakeStore(), object(), system_name="vectone")
    names = {skill["name"] for skill in payload["skills"]}
    assert "custom-skill" in names
    assert "greenfield-website" in names


def test_create_skill_payload_writes_project_skills_index(skills_home):
    from api.skills import create_skill_payload

    class FakeStore:
        def __init__(self):
            self.saved = []

        def upsert_file(self, project_id, user, *, path, content):
            self.saved.append((project_id, path, content))
            return {"path": path, "content": content}

        def list_files(self, project_id, user):
            return [{"path": path, "content": content} for _project_id, path, content in self.saved]

    store = FakeStore()
    payload = create_skill_payload(
        "/create-skill named agentic-architecture for architecture reviews",
        system_name="vectone",
        project_id="project-1",
        store=store,
        user=object(),
    )

    saved_paths = [path for _project_id, path, _content in store.saved]
    assert ".worktual/skills/agentic-architecture/SKILL.md" in saved_paths
    assert ".worktual/skills/skills.md" in saved_paths
    assert payload["project_index_file"]["path"] == ".worktual/skills/skills.md"
    assert "agentic-architecture" in payload["project_index_file"]["content"]
    assert payload["user_home_files"]
    assert any(item["path"] == "agentic-architecture/SKILL.md" for item in payload["user_home_files"])


def test_create_skill_payload_writes_to_user_skills_home(skills_home):
    from api.skills import create_skill_payload

    payload = create_skill_payload("/create-skill named agentic-architecture for architecture reviews", system_name="vectone")
    skill_md = Path(payload["path"])
    assert payload["name"] == "agentic-architecture"
    assert skill_md == skills_home / "agentic-architecture" / "SKILL.md"
    assert skill_md.is_file()
    text = skill_md.read_text(encoding="utf-8")
    assert "name: agentic-architecture" in text
    assert "use web search" in text
    assert "Provide detailed information with proper analysis" in text
    assert (skills_home / "skills.md").is_file()
    assert payload["project_file"]["path"] == ".worktual/skills/agentic-architecture/SKILL.md"
    assert payload["project_file"]["content"] == text


def test_create_skill_payload_upserts_project_worktual_skill(skills_home):
    from api.skills import create_skill_payload

    class FakeStore:
        def __init__(self):
            self.saved = []

        def upsert_file(self, project_id, user, *, path, content):
            self.saved.append((project_id, user, path, content))
            return {"path": path, "content": content}

        def list_files(self, project_id, user):
            return [{"path": path, "content": content} for saved_project_id, _user, path, content in self.saved if saved_project_id == project_id]

    store = FakeStore()
    user = object()

    payload = create_skill_payload(
        "/create-skill named agentic-architecture for architecture reviews",
        system_name="vectone",
        project_id="project-1",
        store=store,
        user=user,
    )

    assert payload["project_saved"] is True
    assert payload["saved_project_file"]["path"] == ".worktual/skills/agentic-architecture/SKILL.md"
    assert store.saved[0][0] == "project-1"
    assert store.saved[0][1] is user
    assert store.saved[0][2] == ".worktual/skills/agentic-architecture/SKILL.md"


def test_create_skill_payload_uses_model_provider_for_skill_content(skills_home):
    from api.skills import create_skill_payload

    class FakeSkillAuthor:
        def generate_json_with_search(self, prompt, *, system_instruction=None, trace_label=""):
            return {
                "name": "ignored-because-explicit-name",
                "description": "Research agentic architecture with current web-backed analysis.",
                "gap_analysis": "- Added explicit research and output requirements.",
                "body_markdown": (
                    "# Agentic Architecture\n\n"
                    "## Gap Analysis\n\n"
                    "- Added explicit research and output requirements.\n\n"
                    "## Purpose\n\n"
                    "Use this skill to research agentic architecture topics with web search and detailed analysis.\n\n"
                    "## Workflow\n\n"
                    "1. Use web search for current facts and recent framework changes.\n"
                    "2. Explain background, key concepts, current state, tradeoffs, risks, implementation steps, recommendations, assumptions, and limitations.\n"
                    "3. Provide source links when web research is used.\n"
                ),
            }

    payload = create_skill_payload(
        "/create-skill named agentic-architecture for architecture reviews",
        system_name="vectone",
        model_provider=FakeSkillAuthor(),
    )
    skill_md = Path(payload["path"])
    text = skill_md.read_text(encoding="utf-8")
    assert payload["model_authored"] is True
    assert payload["name"] == "agentic-architecture"
    assert payload["gap_analysis"]
    assert "Research agentic architecture with current web-backed analysis." in text
    assert "Use this skill to research agentic architecture topics" in text


def test_create_skill_payload_uses_model_name_for_plain_text_skill(skills_home):
    from api.skills import create_skill_payload

    class FakeSkillAuthor:
        def generate_json_with_search(self, prompt, *, system_instruction=None, trace_label=""):
            return {
                "name": "domain-search-research",
                "description": "Research domains with gap analysis, web search, and practical recommendations.",
                "gap_analysis": "- Added when to use the skill.\n- Added web search and final output requirements.",
                "body_markdown": (
                    "# Domain Search Research\n\n"
                    "## Gap Analysis\n\n"
                    "- Added when to use the skill.\n"
                    "- Added web search and final output requirements.\n\n"
                    "## Purpose\n\n"
                    "Use this skill to research domain search topics with web search and detailed analysis.\n\n"
                    "## Workflow\n\n"
                    "1. Clarify the domain search goal and constraints.\n"
                    "2. Use web search for current tools, availability patterns, pricing, and best practices.\n"
                    "3. Explain tradeoffs, risks, implementation steps, recommendations, assumptions, and limitations.\n"
                ),
            }

    payload = create_skill_payload(
        "/create-skill help me deeply analyze domain search topics, compare tools, and recommend next steps",
        system_name="vectone",
        model_provider=FakeSkillAuthor(),
    )

    skill_md = Path(payload["path"])
    text = skill_md.read_text(encoding="utf-8")
    assert payload["name"] == "domain-search-research"
    assert skill_md == skills_home / "domain-search-research" / "SKILL.md"
    assert payload["project_file"]["path"] == ".worktual/skills/domain-search-research/SKILL.md"
    assert "## Gap Analysis" in text
    assert "name: domain-search-research" in text
