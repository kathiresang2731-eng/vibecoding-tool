from __future__ import annotations

from pydantic import BaseModel


class CreateSkillRequest(BaseModel):
  prompt: str
  workspace_root: str | None = None
  system_name: str | None = None
  model: str | None = None
  project_id: str | None = None

