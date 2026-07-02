"""Data models for Worktual agent skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    body: str
    skill_md_path: Path
    root_dir: Path
    scope: str
    paths: tuple[str, ...] = ()
    disable_auto: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "path": str(self.skill_md_path),
            "root": str(self.root_dir),
            "paths": list(self.paths),
            "disable_auto": self.disable_auto,
            "metadata": dict(self.metadata),
        }
