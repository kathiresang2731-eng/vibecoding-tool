from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GeminiFunctionCall:
  call_id: str
  name: str
  arguments: dict[str, Any]
  raw: dict[str, Any] = field(default_factory=dict)
