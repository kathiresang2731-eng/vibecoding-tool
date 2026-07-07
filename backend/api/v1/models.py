from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateRunRequest(BaseModel):
  workspace_id: str = Field(description="Workspace identifier (project_id during Phase 0).")
  prompt: str = ""
  model: str | None = None
  client: str = Field(default="web", description="Calling client surface: web, cli, or ide.")
  session_id: str | None = None
  workspace_access: dict[str, Any] | None = None


class CancelRunRequest(BaseModel):
  workspace_id: str = Field(description="Workspace identifier (project_id during Phase 0).")
  run_id: str | None = None
