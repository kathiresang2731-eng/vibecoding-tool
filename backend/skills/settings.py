"""Skill module settings (env-driven)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .system_name import resolve_system_name

_LEGACY_USER_SKILLS_DIRNAME = ".worktual-skills"
_MODERN_USER_SKILLS_REL = Path(".worktual") / "skills"


def skills_enabled() -> bool:
    return os.environ.get("SKILLS_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def skills_max_injected() -> int:
    try:
        return max(1, int(os.environ.get("SKILLS_MAX_INJECTED", "2")))
    except ValueError:
        return 2


def app_data_skills_home() -> Path:
    return Path(__file__).resolve().parents[2] / ".data" / "worktual-skills"


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _configured_skills_base() -> Path | None:
    configured = os.environ.get("WORKTUAL_SKILLS_DIR", "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def user_skills_home(system_name: str | None = None) -> Path:
    name = resolve_system_name(explicit=system_name)
    configured_base = _configured_skills_base()
    if configured_base is not None:
        return configured_base / name

    if name != "default":
        user_home = Path("/home") / name
        legacy = user_home / _LEGACY_USER_SKILLS_DIRNAME
        if user_home.is_dir() and _is_writable_dir(legacy):
            return legacy

    current_home = Path.home()
    if name == resolve_system_name(explicit=None) and current_home.name == name:
        legacy = current_home / _LEGACY_USER_SKILLS_DIRNAME
        if legacy.is_dir() and _is_writable_dir(legacy):
            return legacy

    app_data = app_data_skills_home() / name
    if _is_writable_dir(app_data):
        return app_data

    # Callers that need to write can handle OSError; read-only discovery stays non-fatal.
    return app_data


def user_skills_read_roots(system_name: str | None = None) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    name = resolve_system_name(explicit=system_name)

    def add(path: Path) -> None:
        key = str(path.expanduser().resolve(strict=False))
        if key in seen or not path.is_dir():
            return
        seen.add(key)
        roots.append(path)

    configured_base = _configured_skills_base()
    if configured_base is not None:
        add(configured_base / name)
        if name != "default":
            add(configured_base)

    if name != "default":
        add(Path("/home") / name / _LEGACY_USER_SKILLS_DIRNAME)
        add(Path("/home") / name / _MODERN_USER_SKILLS_REL)

    add(Path.home() / _LEGACY_USER_SKILLS_DIRNAME)
    add(Path.home() / _MODERN_USER_SKILLS_REL)
    add(app_data_skills_home() / name)
    add(app_data_skills_home())
    return roots


def migrate_legacy_user_skills_home(*, system_name: str | None = None) -> Path:
    if _configured_skills_base() is not None:
        return user_skills_home(system_name)

    target = user_skills_home(system_name)
    if target.is_dir() and any(target.iterdir()):
        return target

    name = resolve_system_name(explicit=system_name)
    legacy_candidates = [
        Path("/home") / name / _LEGACY_USER_SKILLS_DIRNAME if name != "default" else None,
        Path.home() / _LEGACY_USER_SKILLS_DIRNAME,
        Path.home() / _MODERN_USER_SKILLS_REL,
        app_data_skills_home(),
    ]

    for source in legacy_candidates:
        if source is None or not source.is_dir():
            continue
        if source.resolve(strict=False) == target.resolve(strict=False):
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            continue
        return target

    ancient = Path.home() / "worktual-skills"
    if ancient.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(ancient, target, dirs_exist_ok=True)
        except OSError:
            pass

    return target
