from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GateResult:
  gate: str
  status: str
  category: str | None = None
  message: str = ""
  detail: dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> dict[str, Any]:
    return {
      "gate": self.gate,
      "status": self.status,
      "category": self.category,
      "message": self.message,
      "detail": self.detail,
    }
