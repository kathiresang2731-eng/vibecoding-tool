from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserCommand:
  parts: list[str]
  source: str

  @property
  def executable(self) -> str:
    return self.parts[0]

  @property
  def display(self) -> str:
    return " ".join(shlex.quote(part) for part in self.parts)
