from __future__ import annotations

from pydantic import BaseModel


class RecordChatMessageRequest(BaseModel):
  role: str
  content: str = ""
  metadata: dict | None = None
  chat_session_id: str | None = None


class CreateChatSessionRequest(BaseModel):
  title: str = ""

