from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
  id: str
  email: str
  role: str
  display_name: str = ""
  is_active: bool = True
