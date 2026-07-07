from __future__ import annotations

from pydantic import BaseModel


class MemoryPreferenceRequest(BaseModel):
  category: str
  preference: str
  polarity: str = "positive"
  confidence: float = 0.85
  durability: str = "long_term"
  reason: str = ""
  metadata: dict | None = None

