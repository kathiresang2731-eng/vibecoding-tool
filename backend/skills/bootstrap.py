"""Bootstrap ~/.worktual-skills with default skills on first use."""

from __future__ import annotations

from pathlib import Path

try:
    from .manifest import write_skills_index
    from .seed import sync_bundled_skills_from_repo
    from .settings import migrate_legacy_user_skills_home, user_skills_home
except ImportError:
    from skills.manifest import write_skills_index
    from skills.seed import sync_bundled_skills_from_repo
    from skills.settings import migrate_legacy_user_skills_home, user_skills_home

README = """# Worktual Skills

Personal agent skills for the Worktual AI website builder (Cursor/Codex-style).

## Layout

```
~/.worktual-skills/
  skills.md
  my-skill/
    SKILL.md
```

## Invoke

- Opt-in only: use `/skill-name` in chat (e.g. `/greenfield-website`), `@skill:name`, or `.worktual/skills/skill-name`.
- Skills are never applied automatically without explicit user permission.
"""

DEFAULT_SKILLS: dict[str, str] = {
    "greenfield-website": """---
name: greenfield-website
description: Build a new React + Vite website or e-commerce storefront from scratch. Use when the user asks for a website, web app, landing page, dashboard, or storefront with no existing project files.
paths: package.json,src/**,index.html
---

# Greenfield Website

## Workflow

1. Generate a complete, runnable Vite + React project — not a sketch, outline, or single-file demo.
2. Scaffold a full project tree: `index.html`, `package.json`, `vite.config.js`, `tailwind.config.js`, `postcss.config.js`, `src/main.jsx`, `src/index.css`, `src/theme/tokens.js`, `src/App.jsx`, multiple `src/components/*`, `src/pages/*`, and `src/data/*` when needed.
3. Keep `src/App.jsx` as a thin composition shell. Put real UI in dedicated component and page files.
4. Put catalog or sample content in `src/data/*.js` as exported constants.
5. Use Tailwind via `@tailwind` directives in `src/index.css`.
6. For a full website brief, target production-quality output with realistic content — typically 15+ files and 1000+ lines total. Do not artificially limit file count or line count.

## Quality bar

- Responsive layout, realistic sample products/content, accessible buttons and landmarks.
- `vite.config.js` must set `base: '/preview/'`.
- `src/main.jsx` uses `import { createRoot } from 'react-dom/client'`.
- `package.json` must include `vite`, `react`, `react-dom`, `tailwindcss`, `postcss`, and `autoprefixer`.
- Every generated file must be complete and syntactically valid — no placeholders, TODO stubs, or truncated components.
""",
    "session-code-edit": """---
name: session-code-edit
description: Edit an existing codebase in the workspace with minimal diffs. Use for bug fixes, feature tweaks, refactors, and follow-up changes when project files already exist.
paths: src/**,*.js,*.jsx,*.tsx,*.html,*.css
---

# Session Code Edit

## Workflow

1. Read relevant files before editing.
2. Prefer small targeted patches over full rewrites.
3. Never append to `.jsx` / `.js` — patch in place.
4. Match existing naming, imports, and patterns in the repo.
""",
    "worktual-local-workspace": """---
name: worktual-local-workspace
description: Work with a linked local filesystem project path in Worktual. Use when the user connects a local folder, edits files on disk, or asks about syncing generated code to their machine.
paths: **/*
---

# Worktual Local Workspace

## Rules

1. Treat the linked local directory as the source of truth for on-disk files.
2. Write generated files incrementally as they are produced — do not wait for preview success.
3. Preserve unrelated files in the workspace; only change planned paths.
4. When the user mentions their local path, confirm edits land in both the UI panel and disk.
""",
    "create-skill": """---
name: create-skill
description: Create or update a Worktual agent skill under ~/.worktual-skills. Use when the user wants to save a workflow, coding standard, or repeatable instruction as a skill.
disable-model-invocation: true
---

# Create Skill

1. Pick a lowercase hyphenated name.
2. Create `~/.worktual-skills/<name>/SKILL.md`.
3. Also provide the same skill under the active project `.worktual/skills/<name>/SKILL.md` when a project is available.
4. Frontmatter must include `name` and `description`.
5. For topic, technology, product, library, error, or best-practice skills, instruct the LLM to use web search for current information.
6. The generated skill must ask for detailed analysis: background, key concepts, current state, tradeoffs, risks, implementation steps, practical recommendations, assumptions, and limitations.
7. Regenerate the index with `skills.md` after adding skills.
""",
}


_LEGACY_GREENFIELD_MARKERS = (
    "keep each codegen step under 3 files and 120 lines",
    "under 3 files and 120 lines for valid json",
)


def _write_default_skills(home: Path) -> list[str]:
    created: list[str] = []
    for folder, content in DEFAULT_SKILLS.items():
        skill_dir = home / folder
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            continue
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(content.strip() + "\n", encoding="utf-8")
        created.append(folder)
    return created


def _refresh_outdated_default_skills(home: Path) -> list[str]:
    refreshed: list[str] = []
    for folder, content in DEFAULT_SKILLS.items():
        skill_md = home / folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            existing = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        normalized = existing.lower()
        if folder == "greenfield-website" and not any(marker in normalized for marker in _LEGACY_GREENFIELD_MARKERS):
            continue
        skill_md.write_text(content.strip() + "\n", encoding="utf-8")
        refreshed.append(folder)
    return refreshed


def ensure_user_skills_home(
    *,
    workspace_root: Path | None = None,
    system_name: str | None = None,
) -> tuple[Path, dict[str, list[str]]]:
    migrate_legacy_user_skills_home(system_name=system_name)
    home = user_skills_home(system_name)
    home.mkdir(parents=True, exist_ok=True)

    created_defaults = _write_default_skills(home)
    refreshed_defaults = _refresh_outdated_default_skills(home)
    synced_from_repo = sync_bundled_skills_from_repo(home)

    readme = home / "README.md"
    if not readme.is_file():
        readme.write_text(README.strip() + "\n", encoding="utf-8")

    index_path = write_skills_index(home, workspace_root=workspace_root, system_name=system_name)
    return home, {
        "created_defaults": created_defaults,
        "refreshed_defaults": refreshed_defaults,
        "synced_from_repo": synced_from_repo,
        "index_path": [str(index_path)],
    }
