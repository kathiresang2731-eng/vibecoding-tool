from __future__ import annotations

from pydantic import BaseModel


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

