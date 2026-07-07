from __future__ import annotations

from typing import Any

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
  workspace_access: dict[str, Any] | None = None


class ResumeGenerationRequest(BaseModel):
  prompt: str = ""
  thread_id: str | None = None
  model: str | None = None
  model_policy: str = "auto_staged"
  artifact_model: str | None = None
  request_class: str | None = None
  estimated_credit_reservation: float | None = None
  resume_graph: bool = False
