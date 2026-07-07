from __future__ import annotations

from pydantic import BaseModel


class CreateProjectRequest(BaseModel):
  name: str = "Untitled project"
  description: str = ""
  workspace_mode: str = "backend"
  local_path: str | None = None


class UpdateProjectRequest(BaseModel):
  name: str | None = None


class SaveFileRequest(BaseModel):
  content: str


class LocalPathRequest(BaseModel):
  path: str


class CreateLocalDirectoryRequest(BaseModel):
  parent_path: str
  name: str


class LocalSyncRequest(BaseModel):
  direction: str = "pull"
  allow_prune_missing: bool = False


class BrowserDirectoryFile(BaseModel):
  path: str
  content: str


class BrowserDirectoryImportRequest(BaseModel):
  files: list[BrowserDirectoryFile]


class LocalEnvironmentErrorRequest(BaseModel):
  source: str = "local_environment"
  message: str
  operation: str = ""
  workspace_name: str | None = None
  workspace_kind: str | None = None
  system_name: str | None = None
  helper_url: str | None = None
  recommended_action: str | None = None
  details: dict | None = None

