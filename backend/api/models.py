from __future__ import annotations

from pydantic import BaseModel, Field

class PromptAttachment(BaseModel):
  name: str = ""
  mime_type: str = "application/octet-stream"
  content_base64: str = ""
  kind: str = "file"


class GenerateRequest(BaseModel):
  prompt: str = ""
  model: str | None = None
  model_policy: str = "auto_staged"
  artifact_model: str | None = None
  request_class: str | None = None
  estimated_credit_reservation: float | None = None
  confirmation_action: str | None = None
  patch_action: str | None = None
  attachments: list[PromptAttachment] = Field(default_factory=list)


class ResumeGenerationRequest(BaseModel):
  prompt: str = ""
  thread_id: str | None = None
  model: str | None = None
  model_policy: str = "auto_staged"
  artifact_model: str | None = None
  request_class: str | None = None
  estimated_credit_reservation: float | None = None
  resume_graph: bool = False


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


class CreateSkillRequest(BaseModel):
  prompt: str
  workspace_root: str | None = None
  system_name: str | None = None
  model: str | None = None
  project_id: str | None = None


class RecordChatMessageRequest(BaseModel):
  role: str
  content: str = ""
  metadata: dict | None = None
  chat_session_id: str | None = None


class CreateChatSessionRequest(BaseModel):
  title: str = ""


class SignupRequest(BaseModel):
  email: str
  password: str
  display_name: str = ""


class LoginRequest(BaseModel):
  email: str
  password: str


class UpdateProfileRequest(BaseModel):
  email: str | None = None
  display_name: str | None = None
  current_password: str | None = None
  new_password: str | None = None


class AdminCreateUserRequest(BaseModel):
  email: str
  password: str
  display_name: str = ""
  monthly_ai_credits: float | None = None
  daily_token_limit: int | None = None
  weekly_token_limit: int | None = None
  monthly_token_limit: int | None = None


class AdminUpdateUserRequest(BaseModel):
  email: str | None = None
  display_name: str | None = None
  password: str | None = None
  is_active: bool | None = None
  daily_token_limit: int | None = None
  weekly_token_limit: int | None = None
  monthly_token_limit: int | None = None
  monthly_ai_credits: float | None = None
  extend_daily_tokens: int | None = None
  extend_weekly_tokens: int | None = None
  extend_monthly_tokens: int | None = None
  reset_usage: bool = False


class MemoryPreferenceRequest(BaseModel):
  category: str
  preference: str
  polarity: str = "positive"
  confidence: float = 0.85
  durability: str = "long_term"
  reason: str = ""
  metadata: dict | None = None
