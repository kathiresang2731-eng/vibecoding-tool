"""Copy bundled skills from the repository skills1 pack into the user skills home."""

from __future__ import annotations

import shutil
from pathlib import Path


def repo_skills1_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2] / "skills1"
    return candidate if candidate.is_dir() else None


def _should_skip_skill_dir(part: str | Path) -> bool:
    name = part if isinstance(part, str) else part.name
    if name.startswith("."):
        return True
    if name in {"node_modules", "__pycache__"}:
        return True
    return False


def _iter_seed_skill_dirs(pack_root: Path) -> list[Path]:
    discovered: list[Path] = []
    if not pack_root.is_dir():
        return discovered
    for skill_md in sorted(pack_root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        if any(_should_skip_skill_dir(part) for part in skill_dir.relative_to(pack_root).parts):
            continue
        if skill_dir not in discovered:
            discovered.append(skill_dir)
    return discovered


def sync_bundled_skills_from_repo(home: Path) -> list[str]:
    """Copy skills from skills1/* packs when missing in the user home."""
    root = repo_skills1_root()
    if root is None:
        return []

    created: list[str] = []
    pack_roots = [path for path in (root / "skills-cursor", root / "skills_codex") if path.is_dir()]
    for pack_root in pack_roots:
        for source_dir in _iter_seed_skill_dirs(pack_root):
            target_dir = home / source_dir.name
            target_md = target_dir / "SKILL.md"
            if target_md.is_file():
                continue
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
            created.append(source_dir.name)
    return created
