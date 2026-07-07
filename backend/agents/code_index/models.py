from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeChunk:
  project_id: str
  path: str
  symbol: str
  line_start: int
  line_end: int
  content: str
  content_hash: str
  embedding: list[float] = field(default_factory=list)


@dataclass
class CodeMatch:
  path: str
  symbol: str
  line_start: int
  line_end: int
  score: float
  matched_terms: list[str]
  snippets: list[str]
  content_chars: int

  def to_dict(self) -> dict[str, Any]:
    return {
      "path": self.path,
      "symbol": self.symbol,
      "line_start": self.line_start,
      "line_end": self.line_end,
      "score": self.score,
      "matched_terms": self.matched_terms,
      "snippets": self.snippets,
      "content_chars": self.content_chars,
    }
