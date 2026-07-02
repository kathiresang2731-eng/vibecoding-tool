"""Resolve skill directory roots."""

from __future__ import annotations

from pathlib import Path

from .settings import user_skills_home, user_skills_read_roots


def project_skills_roots(workspace_root: Path | None) -> list[Path]:
    if workspace_root is None or not workspace_root.is_dir():
        return []
    candidates = (
        workspace_root / ".worktual" / "skills",
        workspace_root / ".cursor" / "skills",
        workspace_root / ".agents" / "skills",
    )
    return [path for path in candidates if path.is_dir()]


def bundled_skills_root() -> Path:
    return Path(__file__).resolve().parent / "bundled"


def discovery_roots(workspace_root: Path | None = None, *, system_name: str | None = None) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for home in user_skills_read_roots(system_name):
        key = str(home.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        roots.append((home, "user"))
    writable_home = user_skills_home(system_name)
    writable_key = str(writable_home.resolve(strict=False))
    if writable_key not in seen and writable_home.is_dir():
        roots.append((writable_home, "user"))
    for path in project_skills_roots(workspace_root):
        roots.append((path, "project"))
    bundled = bundled_skills_root()
    if bundled.is_dir():
        roots.append((bundled, "bundled"))
    return roots
