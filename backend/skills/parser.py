"""Parse SKILL.md frontmatter and body."""

from __future__ import annotations

import re
from pathlib import Path

from .models import SkillSpec

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()
    raw = match.group(1)
    body = text[match.end() :].strip()
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body


def _parse_paths(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        parts = [item.strip().strip('"').strip("'") for item in inner.split(",")]
        return tuple(p for p in parts if p)
    return tuple(p.strip() for p in value.split(",") if p.strip())


def parse_skill_text(virtual_path: str, text: str, *, scope: str) -> SkillSpec | None:
    meta, body = _parse_frontmatter(text)
    path = Path(virtual_path)
    name = (meta.get("name") or path.parent.name).strip()
    description = (meta.get("description") or "").strip()
    if not name or not description:
        return None

    disable_auto = meta.get("disable-model-invocation", "").lower() in {"true", "yes", "1"}
    paths = _parse_paths(meta.get("paths", ""))
    extra = {
        key: value
        for key, value in meta.items()
        if key not in {"name", "description", "paths", "disable-model-invocation"}
    }

    return SkillSpec(
        name=name,
        description=description,
        body=body,
        skill_md_path=path,
        root_dir=path.parent,
        scope=scope,
        paths=paths,
        disable_auto=disable_auto,
        metadata=extra,
    )


def parse_skill_md(path: Path, *, scope: str) -> SkillSpec | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    return parse_skill_text(str(path), text, scope=scope)
